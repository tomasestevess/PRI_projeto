"""Builds the evaluation pool: top-k of each setup's run file per IN, merged without duplicates.

The run files are the ones written by scripts/solr_query.py with --trec. The display fields are fetched
from the core of the first setup config.

Usage: python scripts/make_pool.py --k 10 --setup configs/setup1.json configs/setup2.json
Writes evaluation/pool.csv with one row per (qid, docid) and one relevance column per rater.
Rows are sorted by docid, not by rank, so raters are not biased by the order of either setup.
"""
import argparse
import csv
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

RATERS = ["rel_A", "rel_B", "rel_C", "rel_D"]
FIELDS = "id,name,neighbourhood_cleansed,price,accommodates,listing_url"


def read_run(path):
    ranks = defaultdict(dict)  # qid -> docid -> rank
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        qid, _, docid, rank, _, _ = line.split()
        ranks[qid][docid] = int(rank)
    return ranks


def fetch_metadata(solr, config, docids):
    params = {"q": "{!terms f=id}" + ",".join(docids), "fq": "doc_type:listing",
              "fl": FIELDS, "rows": len(docids), "wt": "json"}
    body = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    docs = json.loads(urllib.request.urlopen(req, timeout=120).read())["response"]["docs"]
    return {d["id"]: d for d in docs}


def build_pool(names, runs, k):
    pool = defaultdict(dict)  
    for name, run in zip(names, runs):
        for qid, docs in run.items():
            for docid, rank in docs.items():
                if rank <= k:
                    pool[qid].setdefault(docid, {})[name] = rank
    return pool


def write_pool(path, pool, meta, names):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "docid", "name", "neighbourhood_cleansed", "price", "accommodates", "listing_url",
                    *[f"rank_{n}" for n in names], *RATERS, "final"])
        for qid in sorted(pool):
            print(f"{qid}: {len(pool[qid])} unique documents in the pool")
            for docid in sorted(pool[qid]):
                d = meta.get(docid, {})
                w.writerow([qid, docid, d.get("name", ""), d.get("neighbourhood_cleansed", ""),
                            d.get("price", ""), d.get("accommodates", ""), d.get("listing_url", ""),
                            *[pool[qid][docid].get(n, "") for n in names], *[""] * (len(RATERS) + 1)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--setup", nargs="+", default=["configs/setup1.json", "configs/setup2.json"])
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--solr", default="http://localhost:8983/solr")
    ap.add_argument("--out", default="evaluation/pool.csv")
    args = ap.parse_args()

    configs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.setup]
    names = [c["setup"] for c in configs]
    pool = build_pool(names, [read_run(p) for p in args.runs], args.k)

    all_ids = sorted({d for docs in pool.values() for d in docs})
    try:
        meta = fetch_metadata(args.solr.rstrip("/"), configs[0], all_ids) if all_ids else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{configs[0]['setup']}: {e}\n{e.read().decode()[:1500]}")

    write_pool(args.out, pool, meta, names)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
    