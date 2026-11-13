"""Runs a query file (scripts/queries/*.json) against one or more setups and prints the results.

The query file is the same for every setup: the text, the filters and the fields to return. How the text is
matched (analyzers, qf/pf, boosts, nested documents) comes from the "query" block of the setup config.

Usage: python scripts/solr_query.py scripts/queries/rural_quiet.json --setup configs/setup1.json configs/setup2.json
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path


def run(solr, config, query):
    params = {**config["query"]["params"], **query.get("params", {}), "user_q": query["query"],
              "fq": query.get("filter", []), "fl": query["fields"], "rows": query.get("limit", 10),
              "wt": "json"}
    params.setdefault("q", query["query"])  # setup 1: edismax on the text itself
    body = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["response"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="query file")
    ap.add_argument("--setup", nargs="+", required=True)
    ap.add_argument("--solr", default="http://localhost:8983/solr")
    ap.add_argument("--raw", action="store_true", help="print the JSON response")
    args = ap.parse_args()
    query = json.loads(Path(args.query).read_text(encoding="utf-8"))
    for path in args.setup:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            response = run(args.solr.rstrip("/"), config, query)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{config['setup']}: {e}\n{e.read().decode()[:1500]}")
        print(f"\n== {config['setup']}: {response['numFound']} results for {query['query']!r}")
        for d in response["docs"]:
            print(json.dumps(d, ensure_ascii=False) if args.raw else
                  f"{d.get('score', 0):7.2f}  {d.get('id')}  {d.get('name', '')[:50]!r}  "
                  f"{d.get('neighbourhood_cleansed', '')}  {d.get('price', '')}")


if __name__ == "__main__":
    main()
