"""Runs a query file (scripts/queries/*.json) against one or more setups and prints the results.

The query file is the same for every setup: the text, the filters and the fields to return. How the text is
matched (analyzers, qf/pf, boosts, nested documents) comes from the "query" block of the setup config.

With --children N, each listing also returns its N reviews and N POIs that best match the query, ranked by
score, through Solr's [subquery] transformer. The child queries are the ones of the setup config ("review_q" and
"poi_text"), so the children shown are the ones that contributed to the score of the listing. Setups without
nested documents (setup 1) are not affected.

A query file is a JSON object with "query" (the text), "filter" (a list of fq), "fields" (fl) and "limit" (rows).

Usage: python scripts/solr_query.py <query.json> --setup configs/setup1.json configs/setup2.json
       python scripts/solr_query.py <query.json> --setup configs/setup2.json --children 3
       add --trec runs/setup1.run to also write a TREC run file
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

# Pseudo-field returned for each listing -> (doc_type of the children, key of their query in the setup config,
# fields shown)
CHILDREN = {"top_reviews": ("review", "review_q", "id,date,lang,comments_en,score"),
            "top_pois": ("poi", "poi_text", "id,poi_name,category,type,distance_m,wikipedia_title,score")}


def child_params(config, query, n):
    """The [subquery] parameters that return the n best matching children of each listing, and their fl entries.
    Subquery parameters lose their prefix inside the subquery and do not see the top-level ones, so the query
    text is passed again as `<name>.uq` and the setup's child query refers to it as $uq instead of $user_q."""
    setup_params = config["query"]["params"]
    params, fl = {}, []
    for name, (doc_type, key, fields) in CHILDREN.items():
        if key not in setup_params:  # setup without nested documents of this kind
            continue
        params.update({f"{name}.q": setup_params[key].replace("$user_q", "$uq"), f"{name}.uq": query["query"],
                       f"{name}.fq": ["{!term f=_nest_parent_ v=$row.id}", f"doc_type:{doc_type}"],
                       f"{name}.fl": fields, f"{name}.rows": n})
        fl.append(f"{name}:[subquery]")
    return params, fl


def run(solr, config, query, children=0):
    params = {**config["query"]["params"], **query.get("params", {}), "user_q": query["query"],
              "fq": query.get("filter", []), "fl": query["fields"], "rows": query.get("limit", 10),
              "wt": "json"}
    params.setdefault("q", query["query"])  # setup 1: edismax on the text itself
    if children:
        sub, fl = child_params(config, query, children)
        params.update(sub)
        if fl:
            params["fl"] = ",".join([params["fl"], *fl])
    body = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())["response"]


def print_children(doc):
    for name in CHILDREN:
        if name not in doc:
            continue
        sub = doc[name]
        print(f"           {name}: {sub['numFound']} matching")
        for c in sub["docs"]:
            if name == "top_reviews":
                print(f"             {c.get('score', 0):6.2f}  {c.get('date', '')[:10]}  "
                      f"{c.get('comments_en', '')[:110]!r}")
            else:
                print(f"             {c.get('score', 0):6.2f}  {c.get('poi_name', '')!r} "
                      f"({c.get('type', '')}, {c.get('distance_m', 0):.0f} m)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="query file")
    ap.add_argument("--setup", nargs="+", required=True)
    ap.add_argument("--solr", default="http://localhost:8983/solr")
    ap.add_argument("--raw", action="store_true", help="print the JSON response")
    ap.add_argument("--children", type=int, default=0, metavar="N",
                    help="also return the N reviews and N POIs of each listing that best match the query")
    ap.add_argument("--trec", help="append the results to this TREC run file (qid Q0 docid rank score runid)")
    args = ap.parse_args()
    query = json.loads(Path(args.query).read_text(encoding="utf-8"))
    for path in args.setup:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            response = run(args.solr.rstrip("/"), config, query, args.children)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{config['setup']}: {e}\n{e.read().decode()[:1500]}")
        if args.trec:  # qid comes from the file name: in3.setup1.json -> IN3
            qid = Path(args.query).name.split(".")[0].upper()
            with open(args.trec, "a", encoding="utf-8") as f:
                for rank, d in enumerate(response["docs"], 1):
                    f.write(f"{qid} Q0 {d['id']} {rank} {d.get('score', 0):.6f} {config['setup']}\n")
        print(f"\n== {config['setup']}: {response['numFound']} results for {query['query']!r}")
        for d in response["docs"]:
            if args.raw:
                print(json.dumps(d, ensure_ascii=False))
                continue
            print(f"{d.get('score', 0):7.2f}  {d.get('id')}  {d.get('name', '')[:50]!r}  "
                  f"{d.get('neighbourhood_cleansed', '')}  {d.get('price', '')}")
            print_children(d)


if __name__ == "__main__":
    main()
