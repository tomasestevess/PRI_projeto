"""Merges the judgements of every rater (scripts/judge.py) into the qrels: one decision per pooled listing.

Any rater can judge any need. A listing judged once gets that decision. If, by accident, it was judged more than
once with different answers, the most recent answer is kept (unless evaluation/resolutions.csv, with columns
qid, docid, final, note, gives the decision) and the case is listed in evaluation/conflicts.csv. A "?" was saved
as 0, so it counts as not relevant.

Writes evaluation/qrels.txt (TREC: qid 0 docid rel) and says how many pooled listings are still to judge.

Usage: python scripts/merge_judgements.py [--pool evaluation/pool.csv]
"""
import argparse
import csv
import sys
from collections import defaultdict
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
    for path in sorted(d.glob("judgements_*.csv")):
        rater = path.stem.removeprefix("judgements_")
        for r in read_csv(path):
            answers[(r["qid"], r["docid"])].append((r["time"], r["rel"], rater, r["note"]))
    resolved = {(r["qid"], r["docid"]): r["final"] for r in read_csv(d / "resolutions.csv")
                if r.get("final") in ("0", "1")}

    final, conflicts = {}, []
    for key in pool:
        given = sorted(answers.get(key, []))
        if not given:
            continue
        rels = {rel for _, rel, _, _ in given}
        final[key] = resolved.get(key, given[-1][1])
        if len(rels) > 1:
            conflicts.append({"qid": key[0], "docid": key[1],
                              "answers": "; ".join(f"{rater}={rel} ({note})" if note else f"{rater}={rel}"
                                                   for _, rel, rater, note in given),
                              "kept": final[key], "resolved": "yes" if key in resolved else "no (most recent)"})

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
    print(f"\nwrote {d / 'qrels.txt'} ({len(final)} of {len(pool)} pooled listings)"
          + (f"; {len(conflicts)} listings judged differently by two raters, see {d / 'conflicts.csv'}" if conflicts else ""))
    if missing:
        print(f"qrels NOT complete: {missing} pooled listings still to judge (make judge RATER=<letter>)")


if __name__ == "__main__":
    main()
