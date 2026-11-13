"""Defines the explicit Solr schema of a setup (configs/setupN.json) and indexes data/processed/documents.jsonl.

Setup 1 indexes the listings alone; setup 2 sends each listing as a parent document with its reviews and pois
as nested child documents (see configs/ and docs/report_solr_schema.md).

Usage: python scripts/solr_index.py --setup configs/setup2.json [--solr http://localhost:8983/solr]
                                    [--batch 200] [--limit N] [--reset]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # data_processing.py sits at the repo root
import data_processing as dp
from solr_analysis import define_analysis
from translate_reviews import load_translations

DOCS = "data/processed/documents.jsonl"

# Redundant or without value for search. Dropped before indexing, and removed from the schema if left over.
# latitude and longitude are kept in the documents only to build `location`.
DROP = ["price_quote_raw", "price_quote_total_price", "price_quote_price_per_night",
        "price_quote_checkin_date", "price_quote_checkout_date", "latitude", "longitude",
        "minimum_minimum_nights", "maximum_minimum_nights", "minimum_maximum_nights",
        "maximum_maximum_nights", "maximum_nights", "minimum_nights_avg_ntm", "maximum_nights_avg_ntm",
        "hosts_time_as_user_years", "hosts_time_as_user_months", "hosts_time_as_host_years",
        "hosts_time_as_host_months", "host_profile_id", "host_profile_url", "host_picture_url",
        "host_has_profile_pic", "host_id", "host_url", "calculated_host_listings_count",
        "calculated_host_listings_count_entire_homes", "calculated_host_listings_count_private_rooms",
        "calculated_host_listings_count_shared_rooms", "scrape_id", "last_scraped", "calendar_last_scraped",
        "source", "license", "estimated_occupancy_l365d", "estimated_revenue_l365d", "reviewer_id",
        "osm_id", "wikipedia_url"]


def call(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=600).read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e}\n{e.read().decode()[:2000]}")


def schema_fields(schema):
    """The (name, type, extra attributes) of every field of a setup, from its "schema" block."""
    display = set(schema["display_only"])
    not_stored = set(schema["not_stored"])

    def field(name, type_, **kw):
        # Display-only fields are returned in results, never searched, filtered or sorted
        extra = {"indexed": False, "docValues": False} if name in display else {}
        return {"name": name, "type": type_, "stored": name not in not_stored, **extra, **kw}
    fields = [field(n, t) for n, t in schema["text"].items()]
    fields += [field(r["field"], r["type"]) for r in schema["review_text"].values()]
    fields += [field(n, "string") for n in schema["string"]]
    fields += [field(n, "string", multiValued=True) for n in schema["multi_string"]]
    fields += [field(n, "pint") for n in schema["int"]]
    fields += [field(n, "plong") for n in schema["long"]]
    fields += [field(n, "pfloat") for n in schema["float"]]
    fields += [field(n, "pdate") for n in schema["date"]]
    fields.append(field(schema["location"], "location"))
    return fields


def define_schema(solr, config):
    # The _default configset guesses the type of unknown fields (schemaless); here every field is declared
    call(f"{solr}/config", {"set-user-property": {"update.autoCreateFields": "false"}})
    define_analysis(solr, config["analysis"], config["synonyms"])
    for name in DROP:
        if exists(solr, name):
            call(f"{solr}/schema", {"delete-field": {"name": name}})
    # Fields may already exist when the script is rerun, so replace instead of add
    for f in schema_fields(config["schema"]):
        r = json.loads(call(f"{solr}/schema", {"add-field": f}) if not exists(solr, f["name"])
                       else call(f"{solr}/schema", {"replace-field": f}))
        assert "errors" not in r, r


def exists(solr, name):
    try:
        urllib.request.urlopen(f"{solr}/schema/fields/{name}")
        return True
    except urllib.error.HTTPError:
        return False


class PoiDensity:
    """Counts the OSM POIs within dp.POI_RADIUS_M of a listing. The nested pois are capped per category
    by the pipeline, so they cannot be counted to tell a busy area from a rural one."""

    def __init__(self):
        pois = dp.load_pois()
        self.all = cKDTree(dp.to_xyz(pois["latitude"].to_numpy(), pois["longitude"].to_numpy()))
        food = pois[pois["category"] == "food and drink"]
        self.food = cKDTree(dp.to_xyz(food["latitude"].to_numpy(), food["longitude"].to_numpy()))

    def add(self, doc):
        point = dp.to_xyz(np.array([doc["latitude"]]), np.array([doc["longitude"]]))
        doc["poi_count_500m"] = int(self.all.query_ball_point(point, dp.POI_RADIUS_M, return_length=True)[0])
        doc["food_count_500m"] = int(self.food.query_ball_point(point, dp.POI_RADIUS_M, return_length=True)[0])


def clean(doc, date_fields):
    if doc.get("latitude") is not None and doc.get("longitude") is not None:
        doc["location"] = f"{doc['latitude']},{doc['longitude']}"
    for k in DROP:
        doc.pop(k, None)
    for k in date_fields:
        if doc.get(k):
            doc[k] = doc[k][:10] + "T00:00:00Z"
    return doc


def report(solr, start):
    """Prints what the core actually holds per doc_type, the indexing time and the index size."""
    def get(url):
        return json.loads(urllib.request.urlopen(url, timeout=600).read())

    root, core = solr.rstrip("/").rsplit("/", 1)
    facets = get(f"{solr}/select?q=*:*&rows=0&facet=true&facet.field=doc_type")["facet_counts"]["facet_fields"]
    counts = facets["doc_type"]
    print("documents:", dict(zip(counts[::2], counts[1::2])))
    index = get(f"{root}/admin/cores?action=STATUS&core={core}")["status"][core]["index"]
    print(f"indexing time: {time.time() - start:.0f} s, index size: {index['size']}")


def nest(doc, config, translations):
    """Keeps (setup 2) or removes (setup 1) the child documents.

    Only English reviews are kept: those in English, and the translations of the languages in
    `review_translated`, all in comments_en. A review in one of those languages without a translation yet is
    skipped, and so is a review in any other language."""
    schema, dates = config["schema"], config["schema"]["date"]
    reviews, pois = doc.pop("reviews", []), doc.pop("pois", [])
    if config["nested"]["reviews"]:
        kept = []
        for r in reviews:
            comments, lang = r.pop("comments"), r.get("lang")
            if lang in schema["review_translated"]:
                comments = translations.get(r["id"])
            elif lang != "en":
                comments = None
            if comments:
                r["comments_en"] = comments
                kept.append(clean(r, dates))
        doc["reviews"] = kept
    if config["nested"]["pois"]:
        for p in pois:  # own field, so the POI names do not distort the statistics of the listing `name`
            p["poi_name"] = p.pop("name")
        doc["pois"] = [clean(p, dates) for p in pois]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", default="configs/setup2.json", help="configs/setup1.json or configs/setup2.json")
    ap.add_argument("--solr", default="http://localhost:8983/solr", help="Solr base URL; the core is in the setup")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reset", action="store_true", help="delete every document before indexing")
    args = ap.parse_args()

    config = json.loads(Path(args.setup).read_text(encoding="utf-8"))
    solr = f"{args.solr.rstrip('/')}/{config['core']}"
    define_schema(solr, config)
    density = PoiDensity()
    translations = load_translations() if config["nested"]["reviews"] else {}
    print(f"{len(translations)} translated reviews")
    if args.reset:
        call(f"{solr}/update?commit=true", {"delete": {"query": "*:*"}})
    start = time.time()
    batch, total = [], 0
    with open(DOCS, encoding="utf-8") as f:
        for line in f:
            listing = json.loads(line)
            density.add(listing)  # needs latitude and longitude, which clean() drops
            nest(listing, config, translations)
            batch.append(clean(listing, config["schema"]["date"]))
            if len(batch) == args.batch:
                call(f"{solr}/update", batch)
                total += len(batch)
                batch = []
                print(f"{chr(13)}indexed {total}", end="", flush=True)
            if args.limit and total + len(batch) >= args.limit:
                break
    if batch:
        call(f"{solr}/update", batch)
        total += len(batch)
    call(f"{solr}/update", {"commit": {}})
    print(f"{chr(13)}indexed {total} listings into {config['core']}, committed")
    report(solr, start)


if __name__ == "__main__":
    main()
