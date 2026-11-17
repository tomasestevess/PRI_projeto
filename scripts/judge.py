"""Interactive relevance judgement of the evaluation pool, in the terminal.

Each pooled listing needs a single decision, and any rater can judge any need. A rater judges the listings that
no rater has judged yet (it reads every evaluation/judgements_*.csv, so pull the others' files first), one at a time,
need by need, in a random order that is fixed per rater. To split the work, give each rater different needs with
--qids. The screen shows the relevance criteria of the need and, for the listing, what evaluation/pool.csv has:
name, area, price, capacity, link, and the reviews and POIs with words of the query (best first). It never shows which setup
returned the listing or at which rank.

Answers are saved after each one in evaluation/judgements_<rater>.csv (qid, docid, rel, note, time), so the rater
can stop and continue later. scripts/merge_judgements.py then writes the qrels.

Commands (type and press Enter):
  1 / 0       relevant / not relevant
  ?           not sure: saved as 0 with a note, as the criteria ask
  n           add or change the note of the current listing
  r           the 5 most recent reviews of the listing (needs Solr)
  m           more reviews that match the query (needs Solr)
  f <words>   reviews with any of these words, most recent first, e.g. "f noise noisy loud" (needs Solr)
  o           open the listing page in the browser
  b           back to the previous listing      s   skip for now
  h           help                              q   quit (answers are already saved)

Usage: python scripts/judge.py --rater A [--qids IN1 IN3] [--pool evaluation/pool.csv]   (default: every need)
       python scripts/judge.py --rater A --recheck     (go again through this rater's 0 answers)
"""
import argparse
import csv
import json
import os
import random
import re
import shutil
import sys
import textwrap
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from solr_query import EVIDENCE, content_words, word_pattern  # noqa: E402
FIELDS = ["qid", "docid", "rel", "note", "time"]


def width():
    return min(shutil.get_terminal_size((100, 30)).columns, 120) - 2


def wrap(text, indent="  "):
    return "\n".join(textwrap.fill(p, width(), initial_indent=indent, subsequent_indent=indent)
                     for p in str(text).split("\n") if p.strip())


def highlight(text, words):
    """Marks the words of the query in the text (bold yellow; *word* with NO_COLOR set). A word matches by its first
    letters, so "check" also marks "checked" and "arrival" marks "arriving"."""
    pattern = word_pattern(words)
    if not pattern:
        return text
    if os.environ.get("NO_COLOR"):
        return pattern.sub(lambda m: f"*{m.group(0)}*", text)
    return pattern.sub(lambda m: f"\033[1;33m{m.group(0)}\033[0m", text)


def criteria(path):
    """qid -> the text of its section in docs/relevance-criteria.md."""
    text = Path(path).read_text(encoding="utf-8")
    parts = re.split(r"^## (IN\d+):", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip().replace("**", "") for i in range(1, len(parts) - 1, 2)}


def load(path):
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {(r["qid"], r["docid"]): r for r in csv.DictReader(f)}


def save(path, judgements):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(judgements.values(), key=lambda r: (r["qid"], r["docid"])))
    os.replace(tmp, path)


class Solr:
    def __init__(self, url, config):
        self.url, self.core = url.rstrip("/"), config["core"]
        self.review_q = EVIDENCE["review_q"]  # any content word of the query, best match first

    def reviews(self, docid, params):
        params = {"fq": ["doc_type:review", "{!term f=_nest_parent_}" + docid], "fl": "date,comments_en",
                  "wt": "json", **params}
        body = urllib.parse.urlencode(params, doseq=True).encode()
        req = urllib.request.Request(f"{self.url}/{self.core}/select", body,
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())["response"]
        return r["numFound"], r["docs"]


def show_reviews(title, found, docs, words=()):
    print(f"\n{title}: {found} found")
    for d in docs:
        print(highlight(wrap(f"[{d.get('date', '')[:10]}] {d.get('comments_en', '')}", "    "), words))
        print()


def screen(row, pos, total, rater, crit, current, words=()):
    os.system("cls" if os.name == "nt" else "clear")
    qid = row["qid"]
    print(f"Rater {rater} · {qid} · listing {pos} of {total}" + (f" · current answer: {current}" if current else ""))
    print("=" * width())
    print(crit)
    print("=" * width())
    print(f"\n{row['name']}")
    print(f"  {row['neighbourhood_cleansed']} · {row['price']} € per night · {row['accommodates']} guests")
    if row.get("property_type"):
        print(f"  {row['property_type']} · {row['bedrooms'] or '?'} bedrooms · {row['beds'] or '?'} beds · "
              f"check-in rating {row['review_scores_checkin'] or '?'}")
    print(f"  {row['listing_url']}")
    print("\nDescription, sentences with words of the query:")
    print(highlight(wrap(row["description_matches"]), words) if row.get("description_matches") else "  (none)")
    print("\nAmenities with words of the query:")
    print(highlight(wrap(row["amenities_matches"]), words) if row.get("amenities_matches") else "  (none)")
    total = f"; {row['number_of_reviews']} reviews on Airbnb" if row.get("number_of_reviews") else ""
    print(f"\nReviews with words of the query, best first ({row['matching_reviews'] or 0} match{total}):")
    print(highlight(wrap(row["top_reviews"]), words) if row["top_reviews"] else "  (none)")
    if row.get("condition_pois"):
        print("\nPOIs that meet the need's condition (as in the setup 2 query), nearest first:")
        print(wrap(row["condition_pois"]))
    print(f"\nPOIs with words of the query, best first ({row['matching_pois'] or 0} match):")
    print(highlight(wrap(row["top_pois"]), words) if row["top_pois"] else "  (none)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rater", required=True, help="a short name for the rater, e.g. A, B, C or D")
    ap.add_argument("--qids", nargs="+", help="needs to judge (default: every need in the pool)")
    ap.add_argument("--pool", default="evaluation/pool.csv")
    ap.add_argument("--criteria", default="docs/relevance-criteria.md")
    ap.add_argument("--out", help="default: evaluation/judgements_<rater>.csv")
    ap.add_argument("--setup", default="configs/setup2.json", help="setup used to fetch more reviews")
    ap.add_argument("--queries", default="scripts/queries")
    ap.add_argument("--solr", default="http://127.0.0.1:8983/solr")
    ap.add_argument("--recheck", action="store_true",
                    help="go again through the listings this rater judged not relevant (0), to confirm or change them")
    args = ap.parse_args()

    rater = args.rater.upper()
    out = args.out or f"evaluation/judgements_{rater}.csv"
    with open(args.pool, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    qids = args.qids or sorted({r["qid"] for r in rows})
    # one decision per listing: skip what the other raters have already judged
    others = set()
    for path in Path(out).parent.glob("judgements_*.csv"):
        if path.resolve() != Path(out).resolve():
            others |= set(load(path))
    rows = [r for r in rows if r["qid"] in qids and (r["qid"], r["docid"]) not in others]
    if not rows:
        sys.exit(f"nothing to judge for {qids} in {args.pool}: already judged by others, or run make pool first")
    # random order, the same every time for this rater, need by need
    rng = random.Random(f"judge-{rater}")
    order = []
    for qid in qids:
        part = [r for r in rows if r["qid"] == qid]
        rng.shuffle(part)
        order += part
    crit = criteria(args.criteria)
    judgements = load(out)
    config = json.loads(Path(args.setup).read_text(encoding="utf-8"))
    solr = Solr(args.solr, config)
    query_text = {q: json.loads((Path(args.queries) / f"{q.lower()}.{config['setup']}.json")
                                .read_text(encoding="utf-8"))["query"] for q in qids}
    query_words = {q: content_words(text).split() for q, text in query_text.items()}

    if args.recheck:
        order = [r for r in order if judgements.get((r["qid"], r["docid"]), {}).get("rel") == "0"]
        if not order:
            sys.exit("no listings judged 0 by this rater")
    i = 0 if args.recheck else next((k for k, r in enumerate(order) if (r["qid"], r["docid"]) not in judgements),
                                    len(order))
    def forward(k):
        """The next listing to show from position k: in normal mode the next one not judged yet (so the rater does not
        walk again through what is done), in --recheck mode simply the next one."""
        if args.recheck:
            return k
        return next((j for j in range(k, len(order)) if (order[j]["qid"], order[j]["docid"]) not in judgements),
                    len(order))

    history = []  # positions shown before, for "b"
    message = f"{len(others)} listings already judged by other raters are skipped" if others else ""
    while True:
        if i >= len(order):
            missing = [k for k, r in enumerate(order) if (r["qid"], r["docid"]) not in judgements]
            if not missing:
                print(f"\nAll {len(order)} listings judged. Answers in {out}.")
                return
            i = missing[0]
            message = f"{len(missing)} skipped listings left"
        row = order[i]
        key = (row["qid"], row["docid"])
        done = sum(1 for r in order if (r["qid"], r["docid"]) in judgements)
        cur = judgements.get(key)
        screen(row, i + 1, len(order), rater, f"{row['qid']}: {crit.get(row['qid'], '(no criteria found)')}",
               f"{cur['rel']}{' (' + cur['note'] + ')' if cur and cur['note'] else ''}" if cur else "",
               query_words[row["qid"]])
        print(f"\n[{done}/{len(order)} judged, {len(order) - done} left]  1 relevant · 0 not relevant · ? not sure · n note · r recent · "
              f"m more · f <words> · o open · b back · s skip · q quit")
        if message:
            print(message)
            message = ""
        try:
            cmd = input("> ").strip()
        except EOFError:
            print()
            return
        try:
            if cmd in ("1", "0", "?"):
                note = cur["note"] if cur else ""
                if cmd != "?" and note.startswith("?"):
                    note = note.lstrip("? ")
                if cmd == "?":
                    note = input("note (why not sure): ").strip() or note or "?"
                judgements[key] = {"qid": key[0], "docid": key[1], "rel": "0" if cmd == "?" else cmd,
                                   "note": ("? " + note if cmd == "?" and not note.startswith("?") else note),
                                   "time": datetime.now().isoformat(timespec="seconds")}
                save(out, judgements)
                history.append(i)
                i = forward(i + 1)
            elif cmd == "n":
                if not cur:
                    message = "answer 1, 0 or ? first"
                else:
                    cur["note"] = input("note: ").strip()
                    save(out, judgements)
            elif cmd == "b":
                if history:
                    i = history.pop()
                else:
                    message = "no earlier listing in this session"
            elif cmd == "s":
                history.append(i)
                i = forward(i + 1)
            elif cmd == "o":
                webbrowser.open(row["listing_url"])
            elif cmd == "r":
                show_reviews("Most recent reviews", *solr.reviews(row["docid"], {"q": "*:*", "sort": "date desc",
                                                                               "rows": 5}), query_words[row["qid"]])
                input("Enter to go back ")
            elif cmd == "m":
                show_reviews("Reviews that match the query", *solr.reviews(
                    row["docid"], {"q": solr.review_q, "uq": content_words(query_text[row["qid"]]), "rows": 10}),
                    query_words[row["qid"]])
                input("Enter to go back ")
            elif cmd.startswith("f "):
                words = cmd[2:].strip()
                show_reviews(f"Reviews with {words!r}", *solr.reviews(
                    row["docid"], {"q": "{!edismax qf=comments_en mm=1 v=$words}", "words": words,
                                   "sort": "date desc", "rows": 8}), words.split())
                input("Enter to go back ")
            elif cmd == "h":
                print(__doc__)
                input("Enter to go back ")
            elif cmd == "q":
                print(f"Saved in {out}.")
                return
            else:
                message = f"unknown command {cmd!r} (h for help)"
        except (OSError, urllib.error.URLError) as e:
            message = f"Solr is not available ({e}); start it with make solr-up"


if __name__ == "__main__":
    main()
