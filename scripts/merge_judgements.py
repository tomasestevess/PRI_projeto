"""Merges the judgements of the raters (scripts/judge.py) into the final relevance of each pooled listing.

For each need, the two raters of its pair (A and B: IN1 and IN3; C and D: IN2 and IN4) are compared on the listings
both judged: agreement (share of equal answers) and Cohen's kappa, which discounts the agreement expected by chance.
A "?" was saved as 0, so it counts as not relevant.

- Where the two raters agree, that is the final relevance.
- Where they disagree, the listing goes to evaluation/disagreements.csv. The pair discusses it and writes the
  decision in evaluation/resolutions.csv (qid, docid, final, note); this script reads it on the next run.
- evaluation/qrels.txt (TREC: qid 0 docid rel) is written with every listing that has a final relevance. It is
  only complete when every pooled listing was judged by both raters and every disagreement was resolved; until
  then the script says what is missing.

Usage: python scripts/merge_judgements.py [--pool evaluation/pool.csv]
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

PAIRS = {"IN1": ("A", "B"), "IN3": ("A", "B"), "IN2": ("C", "D"), "IN4": ("C", "D")}


def read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def kappa(pairs):
    """Cohen's kappa of a list of (answer_1, answer_2)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    c1, c2 = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(c1[k] * c2[k] for k in set(c1) | set(c2)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="evaluation/pool.csv")
    ap.add_argument("--dir", default="evaluation", help="folder of judgements_<rater>.csv and the outputs")
    args = ap.parse_args()
    d = Path(args.dir)

    pool = read_csv(args.pool)
    names = {(r["qid"], r["docid"]): r["name"] for r in pool}
    judged = {rater: {(r["qid"], r["docid"]): r for r in read_csv(d / f"judgements_{rater}.csv")}
              for rater in "ABCD"}
    resolved = {(r["qid"], r["docid"]): r for r in read_csv(d / "resolutions.csv")}

    final, disagreements, missing = {}, [], Counter()
    all_pairs = []
    print("need  pair  judged by both  agreement  kappa  relevant  disagreements (unresolved)")
    for qid in sorted({r["qid"] for r in pool}):
        r1, r2 = PAIRS[qid]
        docs = sorted(d_ for q, d_ in names if q == qid)
        pairs, unresolved, n_dis = [], 0, 0
        for docid in docs:
            key = (qid, docid)
            a, b = judged[r1].get(key), judged[r2].get(key)
            if not a or not b:
                missing[qid] += 1
                continue
            pairs.append((a["rel"], b["rel"]))
            if a["rel"] == b["rel"]:
                final[key] = a["rel"]
                continue
            n_dis += 1
            if key in resolved and resolved[key]["final"] in ("0", "1"):
                final[key] = resolved[key]["final"]
            else:
                unresolved += 1
            disagreements.append({"qid": qid, "docid": docid, "name": names[key],
                                  "rater_1": r1, "rel_1": a["rel"], "note_1": a["note"],
                                  "rater_2": r2, "rel_2": b["rel"], "note_2": b["note"],
                                  "final": resolved.get(key, {}).get("final", "")})
        all_pairs += pairs
        k = kappa(pairs)
        agree = sum(x == y for x, y in pairs) / len(pairs) if pairs else 0
        rel = sum(1 for doc in docs if final.get((qid, doc)) == "1")
        print(f"{qid}   {r1}+{r2}   {len(pairs):3}/{len(docs):3}        {agree:6.1%}   "
              f"{'  -  ' if k is None else f'{k:5.2f}'}   {rel:5}     {n_dis} ({unresolved})")
    if all_pairs:
        print(f"all   -     {len(all_pairs)} pairs       "
              f"{sum(x == y for x, y in all_pairs) / len(all_pairs):6.1%}   {kappa(all_pairs):5.2f}")

    fields = ["qid", "docid", "name", "rater_1", "rel_1", "note_1", "rater_2", "rel_2", "note_2", "final"]
    with open(d / "disagreements.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(disagreements)
    with open(d / "qrels.txt", "w", encoding="utf-8") as f:
        for (qid, docid), rel in sorted(final.items()):
            f.write(f"{qid} 0 {docid} {rel}\n")

    todo = sum(missing.values()) + sum(1 for r in disagreements if r["final"] not in ("0", "1"))
    print(f"\nwrote {d / 'qrels.txt'} ({len(final)} of {len(pool)} pooled listings) and {d / 'disagreements.csv'}")
    if todo:
        print("qrels NOT complete: " + ", ".join(f"{q}: {n} listings not judged by both raters"
                                                 for q, n in sorted(missing.items())) +
              (", " if missing else "") +
              f"{sum(1 for r in disagreements if r['final'] not in ('0', '1'))} disagreements without a decision "
              f"in {d / 'resolutions.csv'} (columns qid, docid, final, note)")


if __name__ == "__main__":
    main()
