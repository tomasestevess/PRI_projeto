# Fetch the Wikipedia articles for OSM POIs
# Usage: python scripts/fetch_wikipedia.py --raw data/raw

import argparse
import json
import time
from pathlib import Path
import requests

LANGS = ["pt", "en"]  # pt first, en as fallback
CONTACT = "https://github.com/tomasestevess/PRI_projeto"

session = requests.Session()
session.headers["User-Agent"] = f"FEUP-PRI-student-project/0.1 ({CONTACT})"  # without this Wikimedia answers 429

def get(url, params):
    # Get JSON response, with 6 attempts
    for attempt in range(6):
        time.sleep(0.3)  # without a pause the API starts answering 429
        try:
            r = session.get(url, params={**params, "format": "json"}, timeout=60)
            if r.ok and "error" not in r.json():
                return r.json()
            wait = int(r.headers.get("Retry-After", 0))
        except (requests.RequestException, ValueError):
            wait = 0
        time.sleep(wait or 10 * (attempt + 1))
    return None

def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def load_pois(osm_dir):
    # POIs by wikidata qid
    by_qid, by_tag = {}, {}
    files = sorted(osm_dir.glob("pois_*.json"))
    elements = [(p, e) for p in files for e in json.loads(p.read_text(encoding="utf-8"))["elements"]]
    for path, e in elements:
        tags = e.get("tags", {})
        poi = {"city": path.stem.removeprefix("pois_"), "osm": f"{e['type']}/{e['id']}", "name": tags.get("name")}
        for qid in tags.get("wikidata", "").split(";"):
            if qid:
                by_qid.setdefault(qid.strip(), []).append(poi)
        if "wikidata" not in tags and ":" in tags.get("wikipedia", ""):
            by_tag.setdefault(tags["wikipedia"], []).append(poi)
    return by_qid, by_tag

def first_link(entity):
    links = entity.get("sitelinks", {})
    return next(((lang, links[f"{lang}wiki"]["title"]) for lang in LANGS if f"{lang}wiki" in links), None)

def wikidata_jobs(by_qid):
    jobs = []
    qids = sorted(by_qid)
    for i in range(0, len(qids), 50):
        data = get("https://www.wikidata.org/w/api.php", {
            "action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "sitelinks",
            "sitefilter": "|".join(f"{lang}wiki" for lang in LANGS),
        })
        if data is None:  # stop instead of losing 50 POIs; articles.jsonl stays .part, so a rerun resumes
            raise SystemExit("Wikidata API did not answer; run again to resume")
        for qid, entity in data["entities"].items():
            link = first_link(entity)
            if link:
                jobs.append((*link, by_qid[qid]))
    return jobs

def fetch_article(lang, title):
    data = get(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "prop": "extracts|pageprops|info", "explaintext": 1,
        "redirects": 1, "titles": title, "formatversion": 2,  # redirects: otherwise the text is empty
    })
    if data is None:  # stop instead of losing the article; articles.jsonl stays .part, so a rerun resumes
        raise SystemExit(f"Wikipedia API did not answer for {lang}:{title}; run again to resume")
    page = data["query"]["pages"][0]
    if page.get("missing") or page.get("invalid") or not page.get("extract"):
        return None
    return {
        "qid": page.get("pageprops", {}).get("wikibase_item"),
        "lang": lang,
        "title": page["title"],
        "text": page["extract"],
        "url": f"https://{lang}.wikipedia.org/wiki/{page['title'].replace(' ', '_')}",
        "revid": page.get("lastrevid"),
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default="data/raw")
    raw = Path(parser.parse_args().raw)
    out = raw / "wikipedia" / "articles.jsonl"
    part = out.with_name(out.name + ".part")  # written while fetching, so an interrupted run is not taken as complete
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.replace(part)

    by_qid, by_tag = load_pois(raw / "osm")
    tag_jobs = [(*tag.split(":", 1), pois) for tag, pois in by_tag.items()]
    jobs = [job for job in tag_jobs if job[0] in LANGS] + wikidata_jobs(by_qid)  # other languages would never answer

    done = {(a["lang"], a["title"]) for a in read_jsonl(part)} if part.exists() else set()
    todo = [job for job in jobs if job[:2] not in done]
    print(f"{len(todo)} articles to fetch, {len(done)} already done")

    with open(part, "a", encoding="utf-8") as f:
        for i, (lang, title, pois) in enumerate(todo, 1):
            article = fetch_article(lang, title)
            print(f"{i}/{len(todo)} {'skipped: ' if article is None else ''}{lang}:{title}")
            if article:
                f.write(json.dumps({**article, "pois": pois}, ensure_ascii=False) + "\n")
    part.replace(out)

if __name__ == "__main__":
    main()
