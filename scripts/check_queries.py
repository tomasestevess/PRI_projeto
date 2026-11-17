"""Checks the query files, the topics and (optionally) the run files.

Usage: python scripts/check_queries.py [--runs runs/setup1.run runs/setup2.run]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = {"description", "query", "filter", "fields", "limit"}
IN_SCOPE = ["IN1", "IN2", "IN3", "IN5"]
errors = []


def err(msg):
    errors.append(msg)


def check_topics():
    text = (ROOT / "docs/topics/topics.trec").read_text(encoding="utf-8")
    tops = re.findall(r"<top>(.*?)</top>", text, re.S)
    titles = {}
    for t in tops:
        m = {tag: re.search(rf"<{tag}>(.*)", t) for tag in ("num", "title", "desc", "narr")}
        if not all(m.values()):
            err(f"topics.trec: <top> without num/title/desc/narr: {t[:60]!r}")
            continue
        qid = m["num"].group(1).replace("Number:", "").strip()
        titles[qid] = m["title"].group(1).strip().lower()
    if sorted(titles) != IN_SCOPE:
        err(f"topics.trec has {sorted(titles)}, expected {IN_SCOPE}")
    criteria = (ROOT / "docs/relevance-criteria.md").read_text(encoding="utf-8")
    for qid in IN_SCOPE:
        if not re.search(rf"^## {qid}:", criteria, re.M):
            err(f"relevance-criteria.md: missing section {qid}")
    return titles


def check_queries(titles):
    qdir = ROOT / "scripts/queries"
    data = {}
    for qid in IN_SCOPE:
        for s in ("setup1", "setup2"):
            p = qdir / f"{qid.lower()}.{s}.json"
            if not p.exists():
                err(f"missing {p.name}")
                continue
            q = json.loads(p.read_text(encoding="utf-8"))
            data[(qid, s)] = q
            if set(q) - KEYS - {"params"} or KEYS - set(q):
                err(f"{p.name}: keys {sorted(q)} (expected {sorted(KEYS)})")
                continue
            if not isinstance(q["filter"], list) or "doc_type:listing" not in q["filter"]:
                err(f"{p.name}: filter must be a list with doc_type:listing")
            if q["limit"] != 1000:
                err(f"{p.name}: limit is {q['limit']}, TREC runs use 1000 (the pool takes the top 50)")
            if qid in titles and q["query"].strip().lower() != titles[qid]:
                err(f"{p.name}: query {q['query']!r} differs from the topic title {titles[qid]!r}")
            for f in q["filter"]:
                m = re.match(r"city:(\S+)$", f)
                if m and m.group(1) not in ("porto", "lisboa"):
                    err(f"{p.name}: unknown city {m.group(1)!r}")
                if s == "setup1" and re.search(r"\{!(parent|child)", f):
                    err(f"{p.name}: setup 1 is flat, no block join")
    for qid in IN_SCOPE:
        a, b = data.get((qid, "setup1")), data.get((qid, "setup2"))
        if a and b:
            for k in ("query", "fields", "limit"):
                if a.get(k) != b.get(k):
                    err(f"{qid}: '{k}' differs between setup1 and setup2")
            missing = [f for f in a["filter"] if f not in b["filter"]]
            if missing:
                err(f"{qid}: setup2 lacks the setup1 filters {missing}")


def check_runs(paths):
    for path in paths:
        p = Path(path)
        if not p.exists():
            err(f"{path}: not found (run make run-queries)")
            continue
        per_q, seen = {}, set()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            c = line.split(" ")
            if len(c) != 6 or c[1] != "Q0" or not c[3].isdigit():
                err(f"{path}:{n}: not 'qid Q0 docid rank score runid': {line!r}")
                continue
            if (c[0], c[2]) in seen:
                err(f"{path}:{n}: duplicate {c[0]} {c[2]}")
            seen.add((c[0], c[2]))
            per_q.setdefault(c[0], []).append((int(c[3]), float(c[4])))
        if sorted(per_q) != IN_SCOPE:
            err(f"{path}: queries {sorted(per_q)}, expected {IN_SCOPE}")
        for qid, rows in per_q.items():
            if [r[0] for r in rows] != list(range(1, len(rows) + 1)):
                err(f"{path}: {qid} ranks are not 1..n")
            if any(rows[i][1] < rows[i + 1][1] for i in range(len(rows) - 1)):
                err(f"{path}: {qid} scores are not descending")
            print(f"{path}: {qid} -> {len(rows)} results")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", default=[])
    args = ap.parse_args()
    check_queries(check_topics())
    check_runs(args.runs)
    if errors:
        sys.exit("\n".join(["FAILED:"] + errors))
    print("OK")