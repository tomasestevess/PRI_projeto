"""Agreement among all the raters (scripts/judge.py --independent), per information need and overall.

Every rater judged every listing, so the agreement is measured among all of them at once, with Fleiss' kappa (the
generalisation of Cohen's kappa to more than two raters), which corrects the observed agreement for the agreement
expected by chance. For each need, and for all the needs together, it reports:
  raters             how many raters
  listings           listings judged by every rater (a listing missing from any rater's file is left out)
  all_agree          share of those listings on which every rater gave the same answer
  observed_agreement mean, over the listings, of the share of pairs of raters that agree (Fleiss' P-bar)
  fleiss_kappa       (observed - expected by chance) / (1 - expected by chance)
Kappa is nan when all the answers of a need are the same, as then chance agreement is 1. Only listings in the pool
are counted. With --pairs it also writes the agreement of every pair of raters (percent agreement and Cohen's
kappa), which shows if one rater is far from the others.

Usage: python scripts/agreement.py [--pool evaluation/pool.csv] [--dir evaluation] [--pairs]
Writes evaluation/agreement.csv (and evaluation/agreement_pairs.csv with --pairs) and prints the table.
"""
import argparse
import csv
import sys
from itertools import combinations
from pathlib import Path


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fleiss(rows):
    # rows: one tuple of 0/1 answers per listing, all of the same length (the number of raters)
    n, big_n = len(rows[0]), len(rows)
    ones = [sum(r) for r in rows]
    p_i = [(o * o + (n - o) * (n - o) - n) / (n * (n - 1)) for o in ones]
    p1 = sum(ones) / (big_n * n)
    expected = p1 * p1 + (1 - p1) * (1 - p1)
    observed = sum(p_i) / big_n
    kappa = (observed - expected) / (1 - expected) if expected < 1 else float("nan")
    return observed, kappa


def cohen(pairs):
    n = len(pairs)
    observed = sum(x == y for x, y in pairs) / n
    pa = sum(x for x, _ in pairs) / n
    pb = sum(y for _, y in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return observed, ((observed - expected) / (1 - expected) if expected < 1 else float("nan"))


def fmt(value):
    return f"{value:.3f}"


def show(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print("  ".join(f"{h:>18}" for h in fields))
    for r in rows:
        print("  ".join(f"{str(r[h]):>18}" for h in fields))
    print(f"wrote {path}\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="evaluation/pool.csv")
    ap.add_argument("--dir", default="evaluation")
    ap.add_argument("--pairs", action="store_true", help="also the agreement of every pair of raters")
    args = ap.parse_args()
    d = Path(args.dir)

    pool = {(r["qid"], r["docid"]) for r in read_csv(args.pool)}
    judged = {}  # rater -> {(qid, docid): 0 or 1}
    for path in sorted(d.glob("judgements_*.csv")):
        judged[path.stem.removeprefix("judgements_")] = {
            (r["qid"], r["docid"]): int(r["rel"]) for r in read_csv(path)
            if (r["qid"], r["docid"]) in pool and r["rel"] in ("0", "1")}
    raters = sorted(judged)
    if len(raters) < 2:
        sys.exit("need the judgements of at least two raters (evaluation/judgements_<rater>.csv)")
    print(f"raters: {', '.join(raters)}\n")

    every = sorted(k for k in pool if all(k in judged[r] for r in raters))
    for r in raters:
        left = sum(1 for k in pool if k not in judged[r])
        if left:
            print(f"warning: rater {r} has {left} pooled listings still to judge; they are left out\n")

    out = []
    for qid in [*sorted({q for q, _ in pool}), "ALL"]:
        keys = [k for k in every if qid == "ALL" or k[0] == qid]
        if not keys:
            continue
        rows = [tuple(judged[r][k] for r in raters) for k in keys]
        observed, kappa = fleiss(rows)
        out.append({"qid": qid, "raters": len(raters), "listings": len(keys),
                    "all_agree": fmt(sum(len(set(r)) == 1 for r in rows) / len(rows)),
                    "observed_agreement": fmt(observed), "fleiss_kappa": fmt(kappa)})
    show(d / "agreement.csv", ["qid", "raters", "listings", "all_agree", "observed_agreement", "fleiss_kappa"], out)

    if args.pairs:
        pairs = []
        for qid in [*sorted({q for q, _ in pool}), "ALL"]:
            keys = [k for k in every if qid == "ALL" or k[0] == qid]
            for a, b in combinations(raters, 2):
                if keys:
                    observed, kappa = cohen([(judged[a][k], judged[b][k]) for k in keys])
                    pairs.append({"qid": qid, "raters": f"{a}-{b}", "listings": len(keys),
                                  "percent_agreement": fmt(observed), "cohen_kappa": fmt(kappa)})
        show(d / "agreement_pairs.csv", ["qid", "raters", "listings", "percent_agreement", "cohen_kappa"], pairs)


if __name__ == "__main__":
    main()
    