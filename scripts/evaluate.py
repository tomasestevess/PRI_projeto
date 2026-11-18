"""Evaluates the runs of both setups against the qrels.

Metrics (binary relevance, trec_eval definitions; listings missing from the qrels count as not relevant):
  P@k, R@k   relevant listings among the first k / divided by the number of relevant listings
  nDCG@k     binary gain, log2 discount, normalised by the ideal ranking
  R-prec     precision at rank R (R = number of relevant listings)
  RR         reciprocal rank of the first relevant listing (MRR over the needs)
  AP / MAP   mean of the precision at the rank of each relevant listing (relevant listings that are not
             retrieved count as 0), and its mean over the needs
  PR / AUC   11-point interpolated precision-recall curve (recall 0, 0.1, ..., 1) and its area (trapezoid rule)
  judged@k   share of the first k listings that have a judgement. Below 1 means that P@k and nDCG@k are lower
             bounds, because unjudged listings were counted as not relevant.

Also checks the inputs (duplicates in a run, needs without a run, relevant listings that are not in any run) and
writes the comparison between setups (difference per need and wins/losses).

Usage: python scripts/evaluate.py [--qrels evaluation/qrels.txt] [--runs runs/setup1.run runs/setup2.run]
                                  [--ks 10 20 50] [--latex] [--out evaluation]
Writes evaluation/metrics.csv (one row per setup and need, plus "all" = mean over the needs), evaluation/figures/
(PR curves, PNG and PDF), evaluation/comparison.csv and, with --latex, evaluation/metrics.tex.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RECALL = [i / 10 for i in range(11)]
COLORS = ["#C8553D", "#1B3A6B", "#2E8B57", "#8A6BBE"]


def read_qrels(path):
    """Returns (relevant, judged): qid -> set of docids with rel > 0, and qid -> set of all judged docids."""
    relevant, judged = defaultdict(set), defaultdict(set)
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 4:
            sys.exit(f"{path}:{n}: expected 'qid 0 docid rel', got {line!r}")
        qid, _, docid, rel = parts[:4]
        judged[qid].add(docid)
        if int(rel) > 0:
            relevant[qid].add(docid)
    return relevant, judged


def read_run(path):
    """Returns (qid -> docids in rank order without duplicates, number of duplicate rows dropped)."""
    rows = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            parts = line.split()
            if len(parts) < 6:
                sys.exit(f"{path}:{n}: expected 6 TREC columns, got {len(parts)}")
            rows.append(parts)
    ranked, seen, dups = defaultdict(list), defaultdict(set), 0
    # sort by rank, then by file order (sorted() is stable), so equal ranks keep the order of the file
    for qid, _, docid, rank, _, _ in sorted(rows, key=lambda r: (r[0], int(r[3]))):
        if docid in seen[qid]:
            dups += 1  # a duplicate would count one relevant listing twice and push AP and recall above 1
            continue
        seen[qid].add(docid)
        ranked[qid].append(docid)
    return ranked, dups


def evaluate(ids, relevant, judged, ks):
    n_rel = len(relevant)
    hits, precisions, points, first = 0, [], [], None
    gains = []
    for i, d in enumerate(ids, 1):
        g = d in relevant
        gains.append(g)
        if g:
            hits += 1
            precisions.append(hits / i)
            first = first or i
        points.append((hits / n_rel, hits / i))
    ap = sum(precisions) / n_rel
    curve = [max((p for r, p in points if r >= level), default=0.0) for level in RECALL]
    auc = sum((curve[i] + curve[i + 1]) / 2 * 0.1 for i in range(10))
    m = {"ap": ap, "auc": auc, "rr": 1 / first if first else 0.0,
         "rprec": sum(gains[:n_rel]) / n_rel}
    for k in ks:
        top = gains[:k]
        m[f"p@{k}"] = sum(top) / k  # divided by k even when the run is shorter, as trec_eval does
        m[f"r@{k}"] = sum(top) / n_rel
        dcg = sum(1 / math.log2(i + 1) for i, g in enumerate(top, 1) if g)
        idcg = sum(1 / math.log2(i + 1) for i in range(1, min(n_rel, k) + 1))
        m[f"ndcg@{k}"] = dcg / idcg
        m[f"judged@{k}"] = sum(1 for d in ids[:k] if d in judged) / k
    return m, curve


def plot(curves, title, path):
    fig, ax = plt.subplots(figsize=(4.5, 3.4))
    for (setup, curve), color in zip(curves.items(), COLORS):
        ax.step(RECALL, curve, where="post", marker="o", markersize=3, color=color, label=setup)
    ax.set(xlabel="Recall", ylabel="Interpolated precision", title=title, xlim=(0, 1), ylim=(0, 1.05))
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(f"{path}.{ext}", dpi=200)
    plt.close(fig)


def mean_curve_of(curves, qids):
    return [sum(curves[q][i] for q in qids) / len(qids) for i in range(11)]


def write_latex(rows, setups, qids, ks, path):
    cols = [f"p@{ks[-1]}", f"ndcg@{ks[-1]}", "ap"]
    names = {f"p@{ks[-1]}": f"P@{ks[-1]}", f"ndcg@{ks[-1]}": f"nDCG@{ks[-1]}", "ap": "AP"}
    lines = [r"\begin{tabular}{l" + "rrr" * len(setups) + "}", r"\toprule",
             "Need & " + " & ".join(rf"\multicolumn{{3}}{{c}}{{{s}}}" for s in setups) + r" \\",
             " & " + " & ".join(names[c] for _ in setups for c in cols) + r" \\", r"\midrule"]
    for qid in qids + ["all"]:
        by = {s: next(r for r in rows if r["setup"] == s and r["qid"] == qid) for s in setups}
        best = {c: max(by[s][c] for s in setups) for c in cols}
        cells = []
        for s in setups:
            for c in cols:
                v = f"{by[s][c]:.3f}"
                cells.append(rf"\textbf{{{v}}}" if by[s][c] == best[c] and len(setups) > 1 else v)
        label = "MAP" if qid == "all" else qid
        if qid == "all":
            lines.append(r"\midrule")
        lines.append(f"{label} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qrels", default="evaluation/qrels.txt")
    ap.add_argument("--runs", nargs="+", default=["runs/setup1.run", "runs/setup2.run"])
    ap.add_argument("--ks", nargs="+", type=int, default=[10, 20, 50], help="cutoffs for P, R and nDCG")
    ap.add_argument("--out", default="evaluation", help="folder for metrics.csv, comparison.csv and figures/")
    ap.add_argument("--latex", action="store_true", help="also write metrics.tex (booktabs table for the report)")
    args = ap.parse_args()
    ks = sorted(set(args.ks))

    relevant, judged = read_qrels(args.qrels)
    qids = sorted(q for q in relevant if relevant[q])
    if not qids:
        sys.exit(f"no relevant listings in {args.qrels}")
    for q in sorted(set(judged) - set(qids)):
        print(f"warning: {q} has judgements but no relevant listing, left out", file=sys.stderr)

    runs = {}
    for p in args.runs:
        if not Path(p).exists():
            sys.exit(f"{p} not found (run `make run-queries` first)")
        run, dups = read_run(p)
        runs[Path(p).stem] = run
        if dups:
            print(f"warning: {p}: {dups} duplicate rows dropped (kept the best-ranked)", file=sys.stderr)
        for q in qids:
            if not run.get(q):
                print(f"warning: {p} has no results for {q}: all its metrics are 0", file=sys.stderr)
            elif len(run[q]) < max(ks):
                print(f"warning: {p}: {q} returned only {len(run[q])} listings (< {max(ks)})", file=sys.stderr)

    rows, curves = [], defaultdict(dict)  # curves[qid][setup]
    for setup, run in runs.items():
        per_q = []
        for qid in qids:
            m, curve = evaluate(run.get(qid, []), relevant[qid], judged[qid], ks)
            row = {"setup": setup, "qid": qid, "relevant": len(relevant[qid]), **m,
                   **{f"p@r{r:.1f}": v for r, v in zip(RECALL, curve)}}
            rows.append(row)
            per_q.append(row)
            curves[qid][setup] = curve
        mc = mean_curve_of({q: curves[q][setup] for q in qids}, qids)
        mean = {k: sum(r[k] for r in per_q) / len(per_q) for k in per_q[0] if k not in ("setup", "qid", "relevant")}
        # AUC of the mean curve (as before), not the mean of the per-need AUCs; they are equal up to rounding
        mean["auc"] = sum((mc[i] + mc[i + 1]) / 2 * 0.1 for i in range(10))
        mean.update({f"p@r{r:.1f}": v for r, v in zip(RECALL, mc)})
        rows.append({"setup": setup, "qid": "all", "relevant": sum(len(relevant[q]) for q in qids), **mean})
        curves["mean"][setup] = mc

    out = Path(args.out)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    first = ["setup", "qid", "relevant", f"p@{ks[-1]}", "ap", "auc"]  # same leading columns as before
    fields = first + [k for k in rows[0] if k not in first]
    with open(out / "metrics.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    for qid in qids:
        plot(curves[qid], qid, out / "figures" / f"pr_{qid}")
    plot(curves["mean"], "Mean over the information needs", out / "figures" / "pr_mean")

    setups = list(runs)
    get = lambda s, q, k: next(r[k] for r in rows if r["setup"] == s and r["qid"] == q)  # noqa: E731
    kk = ks[-1]
    head = ["need", "rel"] + [f"{s}:{m}" for s in setups for m in (f"P@{kk}", f"nDCG@{kk}", "AP")]
    print("  ".join(f"{h:>14}" if i > 0 else f"{h:6}" for i, h in enumerate(head)))
    for qid in qids + ["all"]:
        vals = [f"{get(s, qid, k):14.3f}" for s in setups for k in (f"p@{kk}", f"ndcg@{kk}", "ap")]
        print(f"{'MAP' if qid == 'all' else qid:6}  {get(setups[0], qid, 'relevant'):>14}  " + "  ".join(vals))
    print("\nother metrics (mean over the needs):")
    for s in setups:
        print(f"  {s}: " + "  ".join(f"{k}={get(s, 'all', k):.3f}" for k in
                                       [f"p@{k}" for k in ks[:-1]] + [f"r@{k}" for k in ks] +
                                       [f"ndcg@{k}" for k in ks[:-1]] + ["rprec", "rr", "auc"]))
    low = [(s, q, k) for s in setups for q in qids for k in ks if get(s, q, f"judged@{k}") < 1]
    if low:
        print("\nwarning: some listings in the top-k have no judgement (counted as not relevant); P@k and nDCG@k are "
              "lower bounds:")
        for s in setups:
            print(f"  {s}: " + "  ".join(f"{q}@{k}={get(s, q, f'judged@{k}'):.2f}" for q in qids for k in ks
                                          if get(s, q, f"judged@{k}") < 1))

    if len(setups) >= 2:
        a, b = setups[0], setups[1]
        comp = []
        for qid in qids + ["all"]:
            comp.append({"qid": qid, **{f"{m}_{b}-{a}": round(get(b, qid, m) - get(a, qid, m), 4)
                                         for m in (f"p@{kk}", f"ndcg@{kk}", "ap")}})
        with open(out / "comparison.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(comp[0]))
            w.writeheader()
            w.writerows(comp)
        print(f"\n{b} minus {a} (AP), per need: " +
              "  ".join(f"{q}={get(b, q, 'ap') - get(a, q, 'ap'):+.3f}" for q in qids))
        wins = sum(get(b, q, "ap") > get(a, q, "ap") for q in qids)
        losses = sum(get(b, q, "ap") < get(a, q, "ap") for q in qids)
        print(f"{b} better on AP in {wins}/{len(qids)} needs, worse in {losses}. With so few needs this is "
              "descriptive, not a significance test.")

    if args.latex:
        write_latex(rows, setups, qids, ks, out / "metrics.tex")
    print(f"\nwrote {out / 'metrics.csv'}, {out / 'comparison.csv'} and {out / 'figures'}/pr_*.png|pdf"
          + (f", {out / 'metrics.tex'}" if args.latex else ""))


if __name__ == "__main__":
    main()