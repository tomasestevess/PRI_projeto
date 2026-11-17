"""Builds the evaluation pool: top-k (default 50) of each setup's run file per IN, merged without duplicates.

The run files are the ones written by scripts/solr_query.py with --trec (make run-queries). For each pooled
listing, the display fields and the reviews and POIs that best match the topic's query are fetched from the
setup with nested documents (setup 2), through Solr's [subquery] transformer (child_params in solr_query.py),
so the raters see the evidence of each listing next to it. The query of each topic is read from its query file,
scripts/queries/<qid>.<setup>.json.

Usage: python scripts/make_pool.py [--k 50] [--children 3] --setup configs/setup1.json configs/setup2.json
Writes evaluation/pool.csv with one row per (qid, docid) and one relevance column per rater.
Rows are sorted by docid, not by rank, and the CSV does not say which setup returned each listing or at which
rank, so raters are not biased by either setup (the ranks stay in the run files).
"""
import argparse
import csv
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from solr_query import child_params

RATERS = ["rel_A", "rel_B", "rel_C", "rel_D"]
FIELDS = "id,name,neighbourhood_cleansed,price,accommodates,listing_url"
REVIEW_CHARS = 600  # longer reviews are cut in the CSV


def read_run(path):
    ranks = defaultdict(dict)
    # qid -> docid -> rank
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        qid, _, docid, rank, _, _ = line.split()
        ranks[qid][docid] = int(rank)
    return ranks


def fetch_metadata(solr, config, docids, query=None, children=0):
    """Display fields of the given listings, from the core of `config`. With a query and children > 0, also the
    `children` reviews and POIs of each listing that best match it, ranked by score ([subquery])."""
    params = {"q": "{!terms f=id}" + ",".join(docids), "fq": "doc_type:listing",
              "fl": FIELDS, "rows": len(docids), "wt": "json"}
    if query and children:
        sub, fl = child_params(config, query, children)
        params.update(sub)
        params["fl"] = ",".join([FIELDS, *fl])
    body = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    docs = json.loads(urllib.request.urlopen(req, timeout=300).read())["response"]["docs"]
    return {d["id"]: d for d in docs}


def build_pool(names, runs, k):
    pool = defaultdict(dict)
    # qid -> docid -> {setup_name: rank}
    for name, run in zip(names, runs):
        for qid, docs in run.items():
            for docid, rank in docs.items():
                if rank <= k:
                    # add the rank of this docid for this setup to the pool for this qid
                    pool[qid].setdefault(docid, {})[name] = rank
    return pool


def children_cells(d):
    """Number of matching reviews and POIs of a listing, and the best ones as text, for the CSV."""
    reviews, pois = d.get("top_reviews", {}), d.get("top_pois", {})
    review_text = "\n\n".join(f"[{r.get('date', '')[:10]}] {r.get('comments_en', '')[:REVIEW_CHARS]}"
                              for r in reviews.get("docs", []))
    poi_text = "\n".join(f"{p.get('poi_name', '')} ({p.get('type', '')}, {p.get('distance_m', 0):.0f} m)"
                         for p in pois.get("docs", []))
    return [reviews.get("numFound", ""), review_text, pois.get("numFound", ""), poi_text]


def write_pool(path, pool, meta):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # write the pool to a CSV file with the specified columns
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "docid", "name", "neighbourhood_cleansed", "price", "accommodates", "listing_url",
                    "matching_reviews", "top_reviews", "matching_pois", "top_pois", *RATERS, "final"])
        for qid in sorted(pool):
            print(f"{qid}: {len(pool[qid])} unique documents in the pool")
            for docid in sorted(pool[qid]):
                d = meta.get(qid, {}).get(docid, {})
                w.writerow([qid, docid, d.get("name", ""), d.get("neighbourhood_cleansed", ""),
                            d.get("price", ""), d.get("accommodates", ""), d.get("listing_url", ""),
                            *children_cells(d), *[""] * (len(RATERS) + 1)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=50, help="pool depth: top k of each run (default 50)")
    ap.add_argument("--children", type=int, default=3,
                    help="reviews and POIs shown per listing, the ones that best match the query (0: none)")
    ap.add_argument("--setup", nargs="+", default=["configs/setup1.json", "configs/setup2.json"])
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--queries", default="scripts/queries", help="folder of the query files <qid>.<setup>.json")
    ap.add_argument("--solr", default="http://localhost:8983/solr")
    ap.add_argument("--out", default="evaluation/pool.csv")
    args = ap.parse_args()

    configs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.setup]
    names = [c["setup"] for c in configs]
    pool = build_pool(names, [read_run(p) for p in args.runs], args.k)

    # Fields and children come from the setup with nested reviews and POIs; the listing fields are the same in
    # every core, so a setup without children only loses the evidence columns
    source = next((c for c in configs if c["nested"]["reviews"] or c["nested"]["pois"]), configs[0])
    meta = {}
    for qid, docs in pool.items():
        query_file = Path(args.queries) / f"{qid.lower()}.{source['setup']}.json"
        query = json.loads(query_file.read_text(encoding="utf-8")) if query_file.exists() else None
        if query is None and args.children:
            print(f"{qid}: no {query_file}, so no reviews or POIs are shown")
        try:
            meta[qid] = fetch_metadata(args.solr.rstrip("/"), source, sorted(docs), query, args.children)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{source['setup']}: {e}\n{e.read().decode()[:1500]}")

    write_pool(args.out, pool, meta)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
