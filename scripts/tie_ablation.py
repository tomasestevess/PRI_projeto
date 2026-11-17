"""Ablation study of the eDisMax `tie` parameter: runs the information needs on both setups with several tie values.

`tie` decides how much the fields that are not the best match add to a document's score: with tie = 0 only the best
field counts (pure disjunction max), with tie = 1 the scores of all fields are summed. Each value is applied the same
way to every information need and to every eDisMax query of a setup (listing text, reviews and POIs), so it is
tested as one configuration, never tuned per query.

For each setup, need and tie value the script records:
  - the TREC run (runs/tie/<setup>.tie<value>.run, top 1000), so the variants can be pooled and evaluated;
  - how much the ranking changes against the reference value of the setup config: shared listings in the top 10
    and top 50, and rank-biased overlap (RBO, p = 0.9), which weighs the top of the list most;
  - the latency: median Solr QTime over --repeat runs;
  - with --qrels (TREC format, from the judged pool), P@10, P@50 and average precision, with unjudged listings as
    not relevant, and the MAP of each setup and tie value.
A setup without the `tie` parameter in its query block is skipped.

Usage: python scripts/tie_ablation.py [--ties 0 0.1 0.2 0.3 0.5 0.7 1] [--qrels evaluation/qrels.txt]
Writes evaluation/tie_ablation.csv and prints a summary per setup and tie value.
"""
import argparse
import csv
import json
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERY_IDS = ["IN1", "IN2", "IN3", "IN4"]


def with_tie(params, tie):
    """The setup's query params with every tie (the `tie` parameter and the tie=... of local params) set to `tie`."""
    out = {}
    for k, v in params.items():
        if k == "tie":
            out[k] = tie
        elif isinstance(v, str):
            out[k] = re.sub(r"\btie=[0-9.]+", f"tie={tie}", v)
        else:
            out[k] = v
    return out


def search(solr, config, query, tie, rows):
    params = {**with_tie(config["query"]["params"], tie), **query.get("params", {}), "user_q": query["query"],
              "fq": query.get("filter", []), "fl": "id,score", "rows": rows, "wt": "json"}
    params.setdefault("q", query["query"])
    body = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(f"{solr}/{config['core']}/select", body,
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    docs = r["response"]["docs"]
    return [d["id"] for d in docs], [d["score"] for d in docs], r["response"]["numFound"], r["responseHeader"]["QTime"]


def rbo(a, b, p=0.9, depth=50):
    """Rank-biased overlap of two rankings, truncated at `depth` (1 = same top of the list)."""
    sa, sb, s = set(), set(), 0.0
    for d in range(1, min(depth, len(a), len(b)) + 1):
        sa.add(a[d - 1])
        sb.add(b[d - 1])
        s += p ** (d - 1) * len(sa & sb) / d
    return (1 - p) * s


def read_qrels(path):
    rel = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, _, docid, grade = line.split()[:4]
            rel.setdefault(qid, {})[docid] = int(grade)
    return rel


def precision(ids, relevant, k):
    return sum(1 for d in ids[:k] if d in relevant) / k


def average_precision(ids, relevant):
    if not relevant:
        return 0.0
    hits, total = 0, 0.0
    for i, d in enumerate(ids, 1):
        if d in relevant:
            hits += 1
            total += hits / i
    return total / len(relevant)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ties", nargs="+", type=float, default=[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0])
    ap.add_argument("--setup", nargs="+", default=["configs/setup1.json", "configs/setup2.json"])
    ap.add_argument("--queries", default="scripts/queries")
    ap.add_argument("--rows", type=int, default=1000)
    ap.add_argument("--repeat", type=int, default=3, help="runs per query for the latency (median)")
    ap.add_argument("--qrels", help="TREC qrels; adds P@10, P@50, AP and MAP")
    ap.add_argument("--solr", default="http://127.0.0.1:8983/solr")
    ap.add_argument("--out", default="evaluation/tie_ablation.csv")
    args = ap.parse_args()

    solr = args.solr.rstrip("/")
    qrels = read_qrels(args.qrels) if args.qrels else None
    rundir = ROOT / "runs" / "tie"
    rundir.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in args.setup:
        config = json.loads((ROOT / path).read_text(encoding="utf-8"))
        if "tie" not in config["query"]["params"]:
            print(f"{config['setup']}: no tie parameter, skipped")
            continue
        reference = float(config["query"]["params"]["tie"])
        ties = sorted(set(args.ties) | {reference})
        results = {}  # (tie, qid) -> ids
        for tie in ties:
            run_lines = []
            for qid in QUERY_IDS:
                query = json.loads((ROOT / args.queries / f"{qid.lower()}.{config['setup']}.json")
                                   .read_text(encoding="utf-8"))
                qtimes = []
                for _ in range(args.repeat):
                    ids, scores, found, qtime = search(solr, config, query, tie, args.rows)
                    qtimes.append(qtime)
                results[(tie, qid)] = ids
                run_lines += [f"{qid} Q0 {d} {r} {s:.6f} {config['setup']}.tie{tie:g}"
                              for r, (d, s) in enumerate(zip(ids, scores), 1)]
                rows.append({"setup": config["setup"], "tie": tie, "qid": qid, "found": found,
                             "qtime_ms": statistics.median(qtimes)})
            (rundir / f"{config['setup']}.tie{tie:g}.run").write_text("\n".join(run_lines) + "\n", encoding="utf-8")
            print(f"{config['setup']} tie={tie:g}: done")
        # comparison with the reference value, and the metrics if there are qrels
        for row in rows:
            if row["setup"] != config["setup"]:
                continue
            ids, ref = results[(row["tie"], row["qid"])], results[(reference, row["qid"])]
            row["top10_shared"] = len(set(ids[:10]) & set(ref[:10]))
            row["top50_shared"] = len(set(ids[:50]) & set(ref[:50]))
            row["rbo"] = round(rbo(ids, ref), 3)
            if qrels is not None:
                relevant = {d for d, g in qrels.get(row["qid"], {}).items() if g > 0}
                row["p10"] = round(precision(ids, relevant, 10), 3)
                row["p50"] = round(precision(ids, relevant, 50), 3)
                row["ap"] = round(average_precision(ids, relevant), 4)
        # listings the other tie values would add to a top-50 pool of the reference value
        for qid in QUERY_IDS:
            extra = set().union(*(results[(t, qid)][:50] for t in ties)) - set(results[(reference, qid)][:50])
            print(f"  {config['setup']} {qid}: the other tie values add {len(extra)} listings to the top-50 pool")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("\nsetup   tie   top10 shared  top50 shared  RBO   QTime ms" + ("   P@10   P@50   MAP" if qrels else ""))
    for setup in dict.fromkeys(r["setup"] for r in rows):
        for tie in dict.fromkeys(r["tie"] for r in rows if r["setup"] == setup):
            rs = [r for r in rows if r["setup"] == setup and r["tie"] == tie]
            line = (f"{setup}  {tie:4.2f}  {statistics.mean(r['top10_shared'] for r in rs):11.1f}  "
                    f"{statistics.mean(r['top50_shared'] for r in rs):12.1f}  {statistics.mean(r['rbo'] for r in rs):4.2f}  "
                    f"{statistics.mean(r['qtime_ms'] for r in rs):8.0f}")
            if qrels:
                line += (f"  {statistics.mean(r['p10'] for r in rs):5.3f}  {statistics.mean(r['p50'] for r in rs):5.3f}"
                         f"  {statistics.mean(r['ap'] for r in rs):5.3f}")
            print(line)
    print(f"\nwrote {out.relative_to(ROOT)} and runs/tie/")


if __name__ == "__main__":
    main()
