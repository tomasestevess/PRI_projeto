"""Evaluates the runs of both setups against the qrels: P@50, AP, MAP, the 11-point precision-recall curve and AUC.

The metrics follow trec_eval's definitions. Listings that are not in the qrels count as not relevant.
  P@50   relevant listings among the first 50, divided by 50
  AP     mean of the precision at the rank of each relevant listing (relevant listings that are not retrieved
         count as 0), and MAP its mean over the needs
  PR     interpolated precision at recall 0, 0.1, ..., 1 (the highest precision at that recall or above)
  AUC    area under that 11-point curve (trapezoid rule)

Usage: python scripts/evaluate.py [--qrels evaluation/qrels.txt] [--runs runs/setup1.run runs/setup2.run]
Writes evaluation/metrics.csv and the precision-recall curves in evaluation/figures/ (one per need and the mean
of each setup, as PNG and PDF), and prints the table.
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RECALL = [i / 10 for i in range(11)]
K = 50


def read_qrels(path):
    relevant = defaultdict(set)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, _, docid, rel = line.split()[:4]
            if int(rel) > 0:
                relevant[qid].add(docid)
    return relevant


def read_run(path):
    ranked = defaultdict(list)  # qid -> docids in rank order
    rows = [line.split() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for qid, _, docid, rank, _, _ in sorted(rows, key=lambda r: (r[0], int(r[3]))):
        ranked[qid].append(docid)
    return ranked


def evaluate(ids, relevant):
    hits, precisions, points = 0, [], []  # points: (recall, precision) at each rank
    for i, d in enumerate(ids, 1):
        if d in relevant:
            hits += 1
            precisions.append(hits / i)
        points.append((hits / len(relevant), hits / i))
    ap = sum(precisions) / len(relevant)
    p_at_k = sum(1 for d in ids[:K] if d in relevant) / K
    curve = [max((p for r, p in points if r >= level), default=0.0) for level in RECALL]
    auc = sum((curve[i] + curve[i + 1]) / 2 * 0.1 for i in range(10))
    return p_at_k, ap, curve, auc


def plot(curves, title, path):
    fig, ax = plt.subplots(figsize=(4.5, 3.4))
    for (setup, curve), color in zip(curves.items(), ["#C8553D", "#1B3A6B"]):
        ax.step(RECALL, curve, where="post", marker="o", markersize=3, color=color, label=setup)
    ax.set(xlabel="Recall", ylabel="Interpolated precision", title=title, xlim=(0, 1), ylim=(0, 1.05))
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(f"{path}.{ext}", dpi=200)
    plt.close(fig)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--qrels", default="evaluation/qrels.txt")
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--out", default="evaluation", help="folder for metrics.csv and figures/")
    args = ap.parse_args()

    relevant = read_qrels(args.qrels)
    runs = {Path(p).stem: read_run(p) for p in args.runs}
    qids = sorted(q for q in relevant if relevant[q])
    if not qids:
        sys.exit(f"no relevant listings in {args.qrels}")

    rows, curves = [], defaultdict(dict)  # curves[qid][setup]
    for setup, run in runs.items():
        for qid in qids:
            p, a, curve, auc = evaluate(run.get(qid, []), relevant[qid])
            rows.append({"setup": setup, "qid": qid, "relevant": len(relevant[qid]),
                         f"p@{K}": round(p, 3), "ap": round(a, 4), "auc": round(auc, 4),
                         **{f"p@r{r:.1f}": round(v, 3) for r, v in zip(RECALL, curve)}})
            curves[qid][setup] = curve
        mean_curve = [sum(curves[q][setup][i] for q in qids) / len(qids) for i in range(11)]
        rows.append({"setup": setup, "qid": "all",
                     "relevant": sum(len(relevant[q]) for q in qids),
                     f"p@{K}": round(sum(r[f"p@{K}"] for r in rows if r["setup"] == setup and r["qid"] != "all")
                                     / len(qids), 3),
                     "ap": round(sum(r["ap"] for r in rows if r["setup"] == setup and r["qid"] != "all") / len(qids), 4),
                     "auc": round(sum((mean_curve[i] + mean_curve[i + 1]) / 2 * 0.1 for i in range(10)), 4),
                     **{f"p@r{r:.1f}": round(v, 3) for r, v in zip(RECALL, mean_curve)}})
        curves["mean"][setup] = mean_curve

    out = Path(args.out)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    with open(out / "metrics.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for qid in qids:
        plot(curves[qid], qid, out / "figures" / f"pr_{qid}")
    plot(curves["mean"], "Mean over the information needs", out / "figures" / "pr_mean")

    print(f"need  relevant  " + "  ".join(f"{s:>8} P@{K}  {s:>8} AP" for s in runs))
    for qid in qids + ["all"]:
        line = [f"{r[f'p@{K}']:13.3f}  {r['ap']:11.3f}" for s in runs for r in rows if r["setup"] == s and r["qid"] == qid]
        rel = next(r["relevant"] for r in rows if r["qid"] == qid)
        print(f"{'MAP' if qid == 'all' else qid:4}  {rel:8}  " + "  ".join(line))
    print("AUC   " + "  ".join(f"{s}: {r['auc']:.3f}" for s in runs for r in rows if r["setup"] == s and r["qid"] == "all"))
    print(f"\nwrote {out / 'metrics.csv'} and {out / 'figures'}/pr_*.png|pdf")


if __name__ == "__main__":
    main()
