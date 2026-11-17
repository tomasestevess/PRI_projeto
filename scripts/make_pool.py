"""Builds the evaluation pool of each information need, to be judged by hand.

The pool of a need has:
  1. the top k (default 50) of each run, merged without duplicates. The runs are the ones of make run-queries
     and, with --extra-runs, other runs to be compared on the same judgements, such as the tie variants of
     scripts/tie_ablation.py (runs/tie/*.run);
  2. a semi-automatic extension: the results ranked k+1 to --tfidf-depth (default 200) in the main runs are
     scored by tf-idf against the topic (title and description in docs/topics/topics.trec), over the name and
     description of each listing, and the --tfidf-n (default 10) best of each need are added, so that relevant
     listings just below the top k are also judged. The rest of those results are not judged.

For each pooled listing, the display fields and the reviews and POIs that best match the topic's query are fetched
from the setup with nested documents (setup 2), through Solr's [subquery] transformer (child_params in
solr_query.py), so the raters see the evidence of each listing next to it. The query of each topic is read from its
query file, scripts/queries/<qid>.<setup>.json.

Usage: python scripts/make_pool.py [--k 50] [--children 3] [--extra-runs "runs/tie/*.run"]
                                   [--tfidf-depth 200] [--tfidf-n 10]
Writes evaluation/pool.csv, with one row per (qid, docid), one relevance column per rater, the final decision and
notes. Rows are sorted by docid, and the CSV does not say which run returned each listing, at which rank or
whether it came from the tf-idf step, so raters are not biased; that is in evaluation/pool_sources.csv.
"""
import argparse
import csv
import glob
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from solr_query import child_params, content_words, word_pattern

RATERS = ["rel_A", "rel_B", "rel_C", "rel_D"]
FIELDS = ("id,name,neighbourhood_cleansed,price,accommodates,number_of_reviews,listing_url,description,amenities,"
          "property_type,bedrooms,beds,review_scores_checkin")
REVIEW_CHARS = 600  # longer reviews are cut in the CSV
CANDIDATES = 5  # children fetched per child shown, as only those with a word of the query are kept


def read_run(path):
    ranks = defaultdict(dict)
    # qid -> docid -> rank
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        qid, _, docid, rank, _, _ = line.split()
        ranks[qid][docid] = int(rank)
    return ranks


def read_topics(path):
    """qid -> title and description of docs/topics/topics.trec."""
    text = Path(path).read_text(encoding="utf-8")
    topics = {}
    for top in re.findall(r"<top>(.*?)</top>", text, re.S):
        qid = re.search(r"<num>\s*Number:\s*(\S+)", top).group(1)
        title = re.search(r"<title>(.*)", top).group(1).strip()
        desc = re.search(r"<desc>\s*Description:(.*)", top).group(1).strip()
        topics[qid] = f"{title} {desc}"
    return topics


def solr_select(solr, config, params):
    body = urllib.parse.urlencode({**params, "wt": "json"}, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())["response"]["docs"]


def fetch_metadata(solr, config, docids, query=None, children=0):
    """Display fields of the given listings, from the core of `config`. With a query and children > 0, also the
    `children` reviews and POIs of each listing with words of the query, best match first ([subquery] with the
    looser EVIDENCE queries of solr_query.py: the setup's own child queries can hide the evidence a rater needs)."""
    params = {"q": "{!terms f=id}" + ",".join(docids), "fq": "doc_type:listing", "fl": FIELDS, "rows": len(docids)}
    if query and children:
        sub, fl = child_params(config, query, children * CANDIDATES, evidence=True)
        params.update(sub)
        cond = poi_condition(query)
        if cond:  # the POIs that meet the need's own condition (e.g. a beach within 500 m), nearest first
            params.update({"near_pois.q": cond, "near_pois.fq": "{!term f=_nest_parent_ v=$row.id}",
                           "near_pois.fl": "poi_name,type,distance_m", "near_pois.sort": "distance_m asc",
                           "near_pois.rows": children})
            fl.append("near_pois:[subquery]")
        params["fl"] = ",".join([FIELDS, *fl])
    return {d["id"]: d for d in solr_select(solr, config, params)}


def poi_condition(query):
    """The POI query of a block join filter of the query file ({!parent ... v='<POI query>'}), or None."""
    for f in query.get("filter", []):
        m = re.match(r"\{!parent\b[^}]*\bv='(.*)'\}$", f)
        if m:
            return m.group(1)
    return None


def condition_cell(d):
    """The POIs of a listing that meet the need's POI condition, as text ("" if the need has none)."""
    near = d.get("near_pois")
    if near is None:
        return ""
    return "\n".join(f"{p.get('poi_name', '')} ({p.get('type', '')}, {p.get('distance_m', 0):.0f} m)"
                     for p in near.get("docs", [])) or "none"


def build_pool(runs, k):
    """qid -> docid -> set of the runs that have it in their top k."""
    pool = defaultdict(lambda: defaultdict(set))
    for name, run in runs.items():
        for qid, docs in run.items():
            for docid, rank in docs.items():
                if rank <= k:
                    pool[qid][docid].add(name)
    return pool


def tfidf_candidates(solr, config, runs, pool, topics, k, depth, n):
    """The n listings of each need, ranked k+1..depth in the main runs and not pooled yet, that are most similar
    to the topic by tf-idf over their name and description: qid -> [(docid, score)]."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import linear_kernel

    chosen = {}
    for qid in sorted(pool):
        cands = sorted({d for run in runs.values() for d, r in run.get(qid, {}).items()
                        if k < r <= depth and d not in pool[qid]})
        if not cands or qid not in topics:
            chosen[qid] = []
            continue
        docs = solr_select(solr, config, {"q": "{!terms f=id}" + ",".join(cands), "fq": "doc_type:listing",
                                          "fl": "id,name,description", "rows": len(cands)})
        texts = {d["id"]: f"{d.get('name', '')} {d.get('description', '')}" for d in docs}
        ids = [c for c in cands if c in texts]
        vec = TfidfVectorizer(stop_words="english", sublinear_tf=True)
        matrix = vec.fit_transform([texts[c] for c in ids] + [topics[qid]])
        scores = linear_kernel(matrix[-1], matrix[:-1]).ravel()  # cosine: the rows are L2-normalised
        ranked = sorted(zip(ids, scores), key=lambda x: -x[1])
        chosen[qid] = [(d, float(s)) for d, s in ranked[:n] if s > 0]
        print(f"{qid}: {len(cands)} results ranked {k + 1}-{depth} not in the pool; tf-idf adds {len(chosen[qid])}")
    return chosen


def children_cells(d, words, n):
    """Number of matching reviews and POIs of a listing, and the n best ones as text, for the CSV. Only reviews
    that contain a word of the query are kept: Solr's stemming also matches other words with the same stem
    ("functioning" and "functional"), which are no evidence."""
    pattern = word_pattern(words)
    keep = (lambda text: bool(pattern.search(text))) if pattern else (lambda text: True)
    reviews, pois = d.get("top_reviews", {}), d.get("top_pois", {})
    review_text = "\n\n".join([f"[{r.get('date', '')[:10]}] {r.get('comments_en', '')[:REVIEW_CHARS]}"
                               for r in reviews.get("docs", []) if keep(r.get("comments_en", ""))][:n])
    # POIs are not filtered: many match through the (Portuguese) text of their Wikipedia article, not their name
    poi_text = "\n".join([f"{p.get('poi_name', '')} ({p.get('type', '')}, {p.get('distance_m', 0):.0f} m)"
                          for p in pois.get("docs", [])][:n])
    return [reviews.get("numFound", ""), review_text, pois.get("numFound", ""), poi_text]


def text_cells(d, words):
    """The sentences of the description and the amenities of a listing that have words of the query."""
    pattern = word_pattern(words)
    if not pattern:
        return ["", ""]
    sentences = re.split(r"(?<=[.!?])\s+", d.get("description", ""))
    return [" [...] ".join(s for s in sentences if pattern.search(s)),
            "; ".join(a for a in d.get("amenities", []) if pattern.search(a))]


def write_pool(path, pool, meta, words, n):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "docid", "name", "neighbourhood_cleansed", "price", "accommodates", "property_type", "bedrooms", "beds",
                    "review_scores_checkin", "number_of_reviews",
                    "listing_url", "description_matches", "amenities_matches",
                    "matching_reviews", "top_reviews", "matching_pois", "top_pois", "condition_pois", *RATERS, "final", "notes"])
        for qid in sorted(pool):
            for docid in sorted(pool[qid]):
                d = meta.get(qid, {}).get(docid, {})
                w.writerow([qid, docid, d.get("name", ""), d.get("neighbourhood_cleansed", ""),
                            d.get("price", ""), d.get("accommodates", ""), d.get("property_type", ""),
                            d.get("bedrooms", ""), d.get("beds", ""), d.get("review_scores_checkin", ""),
                            d.get("number_of_reviews", ""),
                            d.get("listing_url", ""), *text_cells(d, words.get(qid, [])),
                            *children_cells(d, words.get(qid, []), n), condition_cell(d), *[""] * (len(RATERS) + 2)])


def write_sources(path, pool, tfidf):
    scores = {(q, d): s for q, picks in tfidf.items() for d, s in picks}
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "docid", "sources", "tfidf_score"])
        for qid in sorted(pool):
            for docid in sorted(pool[qid]):
                s = scores.get((qid, docid))
                w.writerow([qid, docid, ";".join(sorted(pool[qid][docid])), "" if s is None else f"{s:.4f}"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=50, help="pool depth: top k of each run (default 50)")
    ap.add_argument("--children", type=int, default=3,
                    help="reviews and POIs shown per listing, the ones that best match the query (0: none)")
    ap.add_argument("--setup", nargs="+", default=["configs/setup1.json", "configs/setup2.json"])
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--extra-runs", nargs="*", default=[],
                    help="more runs (or glob patterns, e.g. \"runs/tie/*.run\") whose top k is also pooled")
    ap.add_argument("--tfidf-depth", type=int, default=200, help="last rank of the main runs scored by tf-idf")
    ap.add_argument("--tfidf-n", type=int, default=10, help="listings added per need by tf-idf (0: none)")
    ap.add_argument("--topics", default="docs/topics/topics.trec")
    ap.add_argument("--queries", default="scripts/queries", help="folder of the query files <qid>.<setup>.json")
    ap.add_argument("--solr", default="http://127.0.0.1:8983/solr")
    ap.add_argument("--out", default="evaluation/pool.csv")
    args = ap.parse_args()
    solr = args.solr.rstrip("/")

    configs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.setup]
    main_runs = {Path(p).stem: read_run(p) for p in args.runs}
    extra = sorted({p for pattern in args.extra_runs for p in (glob.glob(pattern) or [pattern])})
    runs = {**main_runs, **{Path(p).stem: read_run(p) for p in extra}}
    pool = build_pool(runs, args.k)
    top_k = {qid: len(docs) for qid, docs in pool.items()}

    # Fields and children come from the setup with nested reviews and POIs; the listing fields are the same in
    # every core, so a setup without children only loses the evidence columns
    source = next((c for c in configs if c["nested"]["reviews"] or c["nested"]["pois"]), configs[0])
    tfidf = {}
    if args.tfidf_n:
        tfidf = tfidf_candidates(solr, source, main_runs, pool, read_topics(args.topics), args.k,
                                 args.tfidf_depth, args.tfidf_n)
        for qid, picks in tfidf.items():
            for docid, _ in picks:
                pool[qid][docid].add("tfidf")

    meta, words = {}, {}
    for qid, docs in pool.items():
        query_file = Path(args.queries) / f"{qid.lower()}.{source['setup']}.json"
        query = json.loads(query_file.read_text(encoding="utf-8")) if query_file.exists() else None
        words[qid] = content_words(query["query"]).split() if query else []
        if query is None and args.children:
            print(f"{qid}: no {query_file}, so no reviews or POIs are shown")
        try:
            meta[qid] = fetch_metadata(solr, source, sorted(docs), query, args.children)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{source['setup']}: {e}\n{e.read().decode()[:1500]}")

    for qid in sorted(pool):
        print(f"{qid}: {len(pool[qid])} listings to judge ({top_k[qid]} from the top {args.k} of "
              f"{len(runs)} runs, {len(pool[qid]) - top_k[qid]} from tf-idf)")
    write_pool(args.out, pool, meta, words, args.children)
    sources = str(Path(args.out).with_name("pool_sources.csv"))
    write_sources(sources, pool, tfidf)
    print(f"wrote {args.out} and {sources}")


if __name__ == "__main__":
    main()
