# Solr schema

Core: `airbnb`. Defined in `scripts/solr_index.py` and `scripts/solr_analysis.py`.

Each listing is a parent document, with its reviews and POIs as nested child documents.
`doc_type` tells them apart: `listing`, `review` or `poi`.

All 57 fields are stored and single-valued, except where noted. `id` is Solr's built-in key.

## Listing

| Field | Type | Notes |
|---|---|---|
| `doc_type` | `string` | Also on reviews and POIs |
| `listing_id` | `plong` | |
| `name`, `description`, `host_about` | `text_multi` | `name` is also on POIs |
| `city`, `neighbourhood_cleansed`, `neighbourhood_group_cleansed` | `string` | |
| `property_type`, `room_type` | `string` | |
| `host_location`, `host_is_superhost`, `host_identity_verified`, `has_availability` | `string` | |
| `bathrooms_text`, `host_name`, `listing_url`, `picture_url` | `string` | Not indexed |
| `amenities` | `string` | Multi-valued |
| `location` | `location` | `lat,lon` |
| `price`, `bathrooms`, `bedrooms`, `beds`, `minimum_nights`, `reviews_per_month`, `host_listings_count` | `pfloat` | |
| `review_scores_rating`, `_accuracy`, `_cleanliness`, `_checkin`, `_communication`, `_location`, `_value` | `pfloat` | |
| `accommodates` | `pint` | |
| `number_of_reviews`, `_ltm`, `_l30d`, `_ly` | `pint` | |
| `availability_30`, `_60`, `_90`, `_365`, `_eoy` | `pint` | |
| `poi_count_500m`, `food_count_500m` | `pint` | Computed at indexing time |
| `first_review`, `last_review` | `pdate` | |

## Review

| Field | Type | Notes |
|---|---|---|
| `comments_en` | `text_en_fold` | English text; machine translated if the review was in fr, pt, es, de, it or nl |
| `lang` | `string` | Original language of the review |
| `date` | `pdate` | |
| `reviewer_name` | `string` | Not indexed |

## POI

| Field | Type | Notes |
|---|---|---|
| `name` | `text_multi` | |
| `category`, `type` | `string` | |
| `distance_m` | `pfloat` | Distance to the listing |
| `wikipedia_title` | `text_multi` | |
| `wikipedia_text` | `text_multi` | Indexed but not stored |

## Text types

| Type | Analysis |
|---|---|
| `text_multi` | Standard tokenizer, lowercase, ASCII folding. No stemming. English and Portuguese synonyms at query time |
| `text_en_fold` | Solr's `text_en` plus ASCII folding. English synonyms at query time |

## Indexing

`data/processed/documents.jsonl` has 2.7 GB. Its 30,590 listings and their children make about 3.3 million Solr documents.

| Decision | Value | Reason |
|---|---|---|
| Batches | 200 listings per request (`--batch`) | The file is read line by line, so the collection is never all in memory |
| Commits | One explicit commit at the end, soft commits disabled in `docker-compose.yml` | Nothing is searched during indexing, so opening searchers would only slow it down |
| Heap | 4 GB (`SOLR_HEAP`) | Solr's default is 512 MB |
| Wikipedia | Text kept on each POI child, indexed but not stored | The repeated text takes 1.22 GB of the file for 2.25 MB of distinct articles. Keeping it on the child lets a block join use it for ranking |
