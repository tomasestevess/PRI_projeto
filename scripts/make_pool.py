"""Builds the evaluation pool: top-k of each setup's run file per IN, merged without duplicates.

Usage: python scripts/make_pool.py --k 10
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
    ranks = defaultdict(dict) 
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        qid, _, docid, rank, _, _ = line.split()
        ranks[qid][docid] = int(rank)
    return ranks


def fetch_metadata(solr, core, docids):
    params = {"q": "{!terms f=id}" + ",".join(docids), "fq": "doc_type:listing",
              "fl": FIELDS, "rows": len(docids), "wt": "json"}
    req = urllib.request.Request(f"{solr}/{core}/select", urllib.parse.urlencode(params).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    docs = json.loads(urllib.request.urlopen(req, timeout=120).read())["response"]["docs"]
    return {d["id"]: d for d in docs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--core", default="airbnb_s1", help="core used to fetch the display fields")
    ap.add_argument("--solr", default="http://localhost:8983/solr")
    ap.add_argument("--out", default="evaluation/pool.csv")
    args = ap.parse_args()

    runs = [read_run(p) for p in args.runs]
    names = [Path(p).stem for p in args.runs]
    pool = defaultdict(dict)  
    for name, run in zip(names, runs):
        for qid, docs in run.items():
            for docid, rank in docs.items():
                if rank <= args.k:
                    pool[qid].setdefault(docid, {})[name] = rank

    all_ids = sorted({d for docs in pool.values() for d in docs})
    meta = fetch_metadata(args.solr.rstrip("/"), args.core, all_ids) if all_ids else {}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
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
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
    