"""Merges the judgements of every rater (scripts/judge.py) into the qrels: one decision per pooled listing.

A listing judged by one rater gets that decision. A listing judged by several raters (scripts/judge.py --independent)
gets the majority decision, and the cases where the raters did not all agree are listed in evaluation/conflicts.csv.
A tie (for example 2 against 2) is not decided by the script: it is kept as 0, like a "?", until the raters agree on it
and write the decision in evaluation/resolutions.csv, with columns qid, docid, final, note. A decision in that file
overrules the majority. A "?" was saved as 0, so it counts as not relevant.

Writes evaluation/qrels.txt (TREC: qid 0 docid rel) and says how many pooled listings are still to judge, how many
have fewer judgements than the number of rater files, and how many ties are still to resolve.

Usage: python scripts/merge_judgements.py [--pool evaluation/pool.csv]
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="evaluation/pool.csv")
    ap.add_argument("--dir", default="evaluation", help="folder of judgements_<rater>.csv and the outputs")
    args = ap.parse_args()
    d = Path(args.dir)

    pool = [(r["qid"], r["docid"]) for r in read_csv(args.pool)]
    answers = defaultdict(list)  # (qid, docid) -> [(time, rel, rater, note)]
    files = sorted(d.glob("judgements_*.csv"))
    for path in files:
        rater = path.stem.removeprefix("judgements_")
        for r in read_csv(path):
            answers[(r["qid"], r["docid"])].append((r["time"], r["rel"], rater, r["note"]))
    resolved = {(r["qid"], r["docid"]): r["final"] for r in read_csv(d / "resolutions.csv")
                if r.get("final") in ("0", "1")}

    final, conflicts, fewer = {}, [], 0
    for key in pool:
        given = sorted(answers.get(key, []), key=lambda a: a[2])  # by rater
        if not given:
            continue
        if len(given) < len(files):
            fewer += 1
        votes = Counter(rel for _, rel, _, _ in given)
        ones, zeros = votes.get("1", 0), votes.get("0", 0)
        if key in resolved:
            final[key], how = resolved[key], "yes"
        elif ones != zeros:
            final[key], how = ("1" if ones > zeros else "0"), "majority"
        else:
            final[key], how = "0", "no (tie, kept 0)"
        if len(votes) > 1:
            conflicts.append({"qid": key[0], "docid": key[1],
                              "answers": "; ".join(f"{rater}={rel} ({note})" if note else f"{rater}={rel}"
                                                   for _, rel, rater, note in given),
                              "kept": final[key], "resolved": how})

    with open(d / "qrels.txt", "w", encoding="utf-8") as f:
        for (qid, docid), rel in sorted(final.items()):
            f.write(f"{qid} 0 {docid} {rel}\n")
    with open(d / "conflicts.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "docid", "answers", "kept", "resolved"])
        w.writeheader()
        w.writerows(conflicts)

    print("need  judged  relevant")
    for qid in sorted({q for q, _ in pool}):
        keys = [k for k in pool if k[0] == qid]
        judged = [k for k in keys if k in final]
        print(f"{qid}   {len(judged):3}/{len(keys):3}  {sum(final[k] == '1' for k in judged):6}")
    missing = len(pool) - len(final)
    ties = sum(c["resolved"].startswith("no") for c in conflicts)
    print(f"\nwrote {d / 'qrels.txt'} ({len(final)} of {len(pool)} pooled listings)")
    if conflicts:
        print(f"{len(conflicts)} listings where the raters did not all agree, see {d / 'conflicts.csv'}: "
              f"{ties} ties still to resolve (add them to {d / 'resolutions.csv'})")
    if fewer:
        print(f"{fewer} listings have fewer judgements than the {len(files)} rater files")
    if missing:
        print(f"qrels NOT complete: {missing} pooled listings still to judge (make judge RATER=<letter>)")


if __name__ == "__main__":
    main()
    