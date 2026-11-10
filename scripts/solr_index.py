"""Defines the Solr schema for the `airbnb` core and indexes data/processed/documents.jsonl.

Each listing is sent as a parent document with its reviews and pois as nested child documents.

Usage: python scripts/solr_index.py [--solr http://localhost:8983/solr/airbnb] [--batch 200] [--limit N]
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

# All reviews go to comments_en, the translated ones with the text from scripts/translate_reviews.py.
# Reviews without a translation are dropped, which covers the languages that are not translated.
REVIEW_LANGS = {"en": "text_en"}
TEXT = ["name", "description", "host_about", "wikipedia_title", "wikipedia_text"]
STRINGS = ["doc_type", "city", "neighbourhood_cleansed", "neighbourhood_group_cleansed", "property_type",
           "room_type", "bathrooms_text", "host_name", "host_location", "host_is_superhost",
           "host_identity_verified", "has_availability", "lang", "category", "type", "reviewer_name",
           "listing_url", "picture_url"]
# Only returned in results, never searched or filtered, so they are stored but not indexed
DISPLAY_ONLY = {"bathrooms_text", "host_name", "reviewer_name", "listing_url", "picture_url"}
MULTI_STRINGS = ["amenities"]
INTS = ["accommodates", "number_of_reviews", "number_of_reviews_ltm", "number_of_reviews_l30d",
        "number_of_reviews_ly", "availability_30", "availability_60", "availability_90",
        "availability_365", "availability_eoy", "poi_count_500m", "food_count_500m"]
LONGS = ["listing_id"]
FLOATS = ["price", "bathrooms", "bedrooms", "beds", "minimum_nights", "reviews_per_month", "distance_m",
          "host_listings_count"] +          [f"review_scores_{k}" for k in
          ["rating", "accuracy", "cleanliness", "checkin", "communication", "location", "value"]]
DATES = ["first_review", "last_review", "date"]
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


def define_schema(solr):
    define_analysis(solr, REVIEW_LANGS)
    def field(name, type_, **kw):
        extra = {"indexed": False, "docValues": False} if name in DISPLAY_ONLY else {}
        return {"name": name, "type": type_, "stored": True, **extra, **kw}
    # wikipedia_text repeats on every POI child near the article, so it is searchable but not stored
    fields = [field(n, "text_multi", stored=n != "wikipedia_text") for n in TEXT]
    fields += [field(f"comments_{lang}", f"{t}_fold") for lang, t in REVIEW_LANGS.items()]
    fields += [field(n, "string") for n in STRINGS]
    fields += [field(n, "string", multiValued=True) for n in MULTI_STRINGS]
    fields += [field(n, "pint") for n in INTS]
    fields += [field(n, "plong") for n in LONGS]
    fields += [field(n, "pfloat") for n in FLOATS]
    fields += [field(n, "pdate") for n in DATES]
    fields.append(field("location", "location"))
    for name in DROP:
        if exists(solr, name):
            call(f"{solr}/schema", {"delete-field": {"name": name}})
    # Fields may already exist when the script is rerun, so replace instead of add
    for f in fields:
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


def clean(doc):
    if doc.get("latitude") is not None and doc.get("longitude") is not None:
        doc["location"] = f"{doc['latitude']},{doc['longitude']}"
    for k in DROP:
        doc.pop(k, None)
    for k in DATES:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solr", default="http://localhost:8983/solr/airbnb")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reset", action="store_true", help="delete every document before indexing")
    args = ap.parse_args()

    define_schema(args.solr)
    density = PoiDensity()
    translations = load_translations()
    print(f"{len(translations)} translated reviews")
    if args.reset:
        call(f"{args.solr}/update?commit=true", {"delete": {"query": "*:*"}})
    start = time.time()
    batch, total = [], 0
    with open(DOCS, encoding="utf-8") as f:
        for line in f:
            listing = json.loads(line)
            density.add(listing)  # needs latitude and longitude, which clean() drops
            batch.append(clean(listing))
            reviews = []
            for r in batch[-1].get("reviews", []):
                comments = r.pop("comments")
                text = comments if r.get("lang") == "en" else translations.get(r["id"])
                if text:
                    r["comments_en"] = text
                    reviews.append(r)
            batch[-1]["reviews"] = reviews
            for child in reviews + batch[-1].get("pois", []):
                clean(child)
            if len(batch) == args.batch:
                call(f"{args.solr}/update", batch)
                total += len(batch)
                batch = []
                print(f"\rindexed {total}", end="", flush=True)
            if args.limit and total + len(batch) >= args.limit:
                break
    if batch:
        call(f"{args.solr}/update", batch)
        total += len(batch)
    call(f"{args.solr}/update", {"commit": {}})
    print(f"\rindexed {total} listings, committed")
    report(args.solr, start)


if __name__ == "__main__":
    main()
