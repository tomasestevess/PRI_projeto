"""Evaluates the run files against the judgements in the pool sheet.

Reads evaluation/pool.csv (written by make_pool.py, with the raters' columns and the agreed "final" column) and
the TREC run files written by solr_query.py (runs/setup1.run, runs/setup2.run).

- qrels: the "final" column (1 = relevant, 0 = not relevant) is the ground truth; they are also written to
  evaluation/qrels.txt in TREC format (qid 0 docid rel).
- metrics at cutoff k (default 10, the depth of the pool): P@5, P@k, AP@k and nDCG@k, per IN and per setup, plus
  the mean over the INs. A missing result counts as not relevant.
- recall is measured against the relevant documents found in the pool (pooled recall), so AP@k divides by that
  number, and the precision-recall curves are 11-point interpolated over the top k only.
- agreement between the two raters of each pair (A-B on IN1/IN3, C-D on IN2/IN5): percent agreement and Cohen's kappa.

Usage: python scripts/evaluate.py --k 10
       python scripts/evaluate.py --demo      (fills empty judgements at random, to test the script with made-up qrels;
                                              writes to evaluation/demo/ and never writes qrels.txt)
"""
import argparse
import csv
import math
import random
from collections import defaultdict
from pathlib import Path

PAIRS = {"IN1": ("rel_A", "rel_B"), "IN3": ("rel_A", "rel_B"),
         "IN2": ("rel_C", "rel_D"), "IN5": ("rel_C", "rel_D")}


def read_run(path):
    # TREC run file: qid Q0 docid rank score runid -> (runid, {qid: [docid sorted by rank]})
    ranked = defaultdict(list)
    name = Path(path).stem
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        qid, _, docid, rank, _, name = line.split()
        ranked[qid].append((int(rank), docid))
    return name, {qid: [d for _, d in sorted(docs)] for qid, docs in ranked.items()}


def fill_demo(rows, rng):
    # only for testing: random judgements where the sheet is still empty
    for r in rows:
        for col in PAIRS.get(r["qid"], ()):
            if r[col] == "":
                r[col] = str(rng.randint(0, 1))
        if r["final"] == "" and r["qid"] in PAIRS:
            r["final"] = r[PAIRS[r["qid"]][0]]


def build_qrels(rows):
    qrels = defaultdict(dict)
    missing = defaultdict(int)
    for r in rows:
        if r["final"].strip() in ("0", "1"):
            qrels[r["qid"]][r["docid"]] = int(r["final"])
        else:
            missing[r["qid"]] += 1
    return qrels, missing


def precision_at(rels, n):
    return sum(rels[:n]) / n


def average_precision(rels, total_rel):
    if total_rel == 0:
        return 0.0
    hits, total = 0, 0.0
    for i, rel in enumerate(rels, 1):
        if rel:
            hits += 1
            total += hits / i
    return total / total_rel


def ndcg_at(rels, total_rel, k):
    dcg = sum(rel / math.log2(i + 1) for i, rel in enumerate(rels[:k], 1))
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(total_rel, k) + 1))
    return dcg / ideal if ideal else 0.0


def pr_curve(rels, total_rel):
    # 11-point interpolated precision at recall 0.0, 0.1, ..., 1.0
    hits, points = 0, []
    for i, rel in enumerate(rels, 1):
        hits += rel
        points.append((hits / total_rel, hits / i))
    return [max([p for r, p in points if r >= level / 10], default=0.0) for level in range(11)]


def agreement(rows, qid, a, b):
    pairs = [(int(r[a]), int(r[b])) for r in rows
             if r["qid"] == qid and r[a].strip() in ("0", "1") and r[b].strip() in ("0", "1")]
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(x == y for x, y in pairs) / n
    pa = sum(x for x, _ in pairs) / n
    pb = sum(y for _, y in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else float("nan")
    return n, observed, kappa


def plot_pr(curves, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed: skipping the precision-recall plot")
        return
    qids = sorted(curves)
    fig, axes = plt.subplots(1, len(qids), figsize=(4 * len(qids), 3.5), squeeze=False)
    for ax, qid in zip(axes[0], qids):
        for name, values in curves[qid].items():
            ax.plot([i / 10 for i in range(11)], values, marker="o", markersize=3, label=name)
        ax.set_title(qid)
        ax.set_xlabel("recall (pooled)")
        ax.set_ylabel("interpolated precision")
        ax.set_ylim(0, 1.05)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"wrote {path}")


def fmt(value):
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--pool", default="evaluation/pool.csv")
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--out", default="evaluation")
    ap.add_argument("--demo", action="store_true", help="fill empty judgements at random, to test the script")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(args.pool, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = Path(args.out) / ("demo" if args.demo else "")
    out.mkdir(parents=True, exist_ok=True)
    if args.demo:
        print("DEMO MODE: empty judgements are random, these numbers mean nothing\n")
        fill_demo(rows, random.Random(args.seed))

    qrels, missing = build_qrels(rows)
    for qid, n in sorted(missing.items()):
        print(f"warning: {qid} has {n} pool rows without a final judgement")
    if not qrels:
        raise SystemExit("no judgements found: fill the 'final' column of the pool sheet first")
    if not args.demo:
        with open(out / "qrels.txt", "w", encoding="utf-8") as f:
            for qid in sorted(qrels):
                for docid, rel in sorted(qrels[qid].items()):
                    f.write(f"{qid} 0 {docid} {rel}\n")
        print(f"wrote {out / 'qrels.txt'}")

    setups = [read_run(p) for p in args.runs]
    cutoffs = sorted({min(5, args.k), args.k})
    results, curves = [], defaultdict(dict)
    for qid in sorted(qrels):
        total_rel = sum(qrels[qid].values())
        for name, ranking in setups:
            top = ranking.get(qid, [])[:args.k]
            rels = [qrels[qid].get(d, 0) for d in top]
            res = {"qid": qid, "setup": name, "relevant_in_pool": total_rel,
                   "unjudged_in_top_k": sum(d not in qrels[qid] for d in top),
                   **{f"P@{n}": precision_at(rels, n) for n in cutoffs},
                   f"AP@{args.k}": average_precision(rels, total_rel),
                   f"nDCG@{args.k}": ndcg_at(rels, total_rel, args.k)}
            results.append(res)
            if total_rel:
                curves[qid][name] = pr_curve(rels, total_rel)

    metric_cols = [f"P@{n}" for n in cutoffs] + [f"AP@{args.k}", f"nDCG@{args.k}"]
    for name, _ in setups:  # mean over the INs: MAP is the mean of AP@k
        own = [r for r in results if r["setup"] == name]
        results.append({"qid": "MEAN", "setup": name, "relevant_in_pool": "", "unjudged_in_top_k": "",
                        **{c: sum(r[c] for r in own) / len(own) for c in metric_cols}})

    header = ["qid", "setup", "relevant_in_pool", "unjudged_in_top_k", *metric_cols]
    print("\n" + "  ".join(f"{h:>16}" for h in header))
    for r in results:
        print("  ".join(f"{fmt(r[h]):>16}" for h in header))
    with open(out / "metrics.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(results)
    print(f"\nwrote {out / 'metrics.csv'}")

    print("\nagreement between raters")
    with open(out / "agreement.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "raters", "judged_by_both", "percent_agreement", "cohen_kappa"])
        for qid in sorted(PAIRS):
            a, b = PAIRS[qid]
            res = agreement(rows, qid, a, b)
            if res is None:
                print(f"{qid} ({a} vs {b}): no documents judged by both yet")
                continue
            n, observed, kappa = res
            print(f"{qid} ({a} vs {b}): {n} documents, agreement {observed:.1%}, kappa {fmt(kappa)}")
            w.writerow([qid, f"{a}-{b}", n, f"{observed:.3f}", fmt(kappa)])
    print(f"wrote {out / 'agreement.csv'}")

    plot_pr(curves, out / "pr_curves.png")


if __name__ == "__main__":
    main()
    