# Document model, schema and linguistic analysis

## 1. Document model

The collection joins three sources: Inside Airbnb (listings, reviews), OpenStreetMap (POIs) and Wikipedia
(articles about POIs). The unit the user wants back is the **listing**, so the index is a
parent–child (block join) model: one Solr document per listing, with its reviews and nearby POIs
as nested child documents (`doc_type` = `listing` | `review` | `poi`).

| Entity | Documents | Source of its text |
|---|---|---|
| listing (parent) | 30,590 (Lisbon 18,872, Porto 11,718) | `name`, `description`, `host_about` |
| review (child) | 2,403,239 | `comments`, one language per review |
| POI (child) | 899,193 listing–POI links (≤ 500 m; the 5 nearest per category plus every POI with an article) | OSM name; Wikipedia title and text for the 831 POIs with an article |

Nesting lets a query such as "quiet, near the Ribeira" use evidence that lives outside the listing (what guests
wrote, what is around) and still return listings: `{!parent which=doc_type:listing}` scores the children and
hands the score to the parent.

## 2. Schema

The schema is explicit: the `_default` configset's schemaless guessing is switched off
(`update.autoCreateFields=false`) and every field is declared by `scripts/solr_index.py` from the `schema`
block of the setup file (`configs/setup1.json`, `configs/setup2.json`). Setup 1 declares 48 fields, setup 2
declares 58.

### 2.1 Criterion

Each field has exactly one role, decided by what users do with it:

| Role | Criterion | Solr treatment |
|---|---|---|
| **Searchable** | natural-language text that a user can describe an information need with, so relevance (BM25) must be computed on it | `TextField` with an analyzer; indexed and stored |
| **Filterable / sortable** | a discrete, numeric, date or geographic value used as a hard constraint, a facet or a sort key. Analysis would only corrupt it (a stemmed `room_type` no longer matches the exact value) | `string`, `pint`, `pfloat`, `pdate`, `location`; indexed with `docValues` (BKD trees for numbers and points) |
| **Display only** | shown in the result card but never searched, filtered or sorted | stored only: `indexed=false`, `docValues=false`. Saves index size and indexing time |

A field that could be both free text and a constraint takes the role that matches the queries in
`scripts/queries/` (e.g. `host_location` is only used as a facet value, so it is a string).

### 2.2 Assignment

| Role | Fields | Why |
|---|---|---|
| Searchable | `name`, `description`, `host_about` (listing) | what hosts say about the place; the vocabulary users query ("apartamento", "quiet", "terrace") |
| Searchable (setup 2 only) | `comments_en` (review); `poi_name`, `wikipedia_title`, `wikipedia_text` (POI) | guest experience ("noisy at night", "perto do rio"); landmarks ("Ribeira") and what they are |
| Filterable | `doc_type`, `city`, `neighbourhood_cleansed`, `neighbourhood_group_cleansed`, `property_type`, `room_type`, `host_location`, `host_is_superhost`, `host_identity_verified`, `has_availability`, `amenities` (multi-valued), `lang`, `category`, `type` | closed vocabularies: exact match and facets |
| Filterable / sortable | `price`, `accommodates`, `bedrooms`, `beds`, `bathrooms`, `minimum_nights`, `availability_*`, `number_of_reviews*`, `reviews_per_month`, `review_scores_*`, `host_listings_count`, `distance_m` | range filters, sorting, and the `boost` function |
| Filterable / sortable | `first_review`, `last_review`, `date` (`pdate`) | recency |
| Filterable / sortable | `location` (`LatLonPointSpatialField`) | `geofilt`, `geodist` |
| Filterable / sortable | `poi_count_500m`, `food_count_500m` | density of the surroundings, computed over *all* OSM POIs (the nested POIs are capped per category, so they cannot be counted to tell a busy area from a rural one). Used by `rural_quiet.json` |
| Display only | `listing_url`, `picture_url`, `host_name`, `bathrooms_text`, `reviewer_name` | URLs and names are identifiers, not information needs; `bathrooms_text` is the text form of `bathrooms`, which is filterable |
| Dropped before indexing | `price_quote_*`, `latitude`/`longitude` (kept as `location`), the other `*_nights` variants, `host_id`/`host_url`/profile fields, `scrape_id`, `source`, `license`, `estimated_*`, `reviewer_id`, `osm_id`, `wikipedia_url`, ... (`DROP` in `solr_index.py`) | redundant or no search value |

POI names go to `poi_name` instead of `name`: with a shared field the POI names would enter the
document-frequency statistics (idf) of the listing `name` and distort its scoring. Review text has its own
fields for the same reason, and because the analyzer is chosen per field.
`wikipedia_text` is searchable but not stored: it repeats on every POI child near an article (1.22 GB of the
documents file for 2.25 MB of distinct articles) and is never shown.

## 3. Linguistic analysis

Types are defined in `scripts/solr_analysis.py` and selected in the `analysis` block of each setup file.

### 3.1 What the data says (M1 EDA)

| Text | Language profile | Source |
|---|---|---|
| Reviews | en 57.3 %, fr 15.5 %, pt 7.7 %, es 7.6 %, de 5.5 %, it 1.8 %, nl 1.5 % = **96.9 %**; the other 3.1 % are spread over ~80 languages (largest: ko 0.9 %; ru, zh, pl 0.3 % each) and are discarded | `analysis/tables/processed/review_languages_pct.csv` |
| Listing `description` | en 99.1 % (Lisbon), 98.8 % (Porto), in a sample of 3,000 listings per city | `airbnb_description_languages_heuristic.csv` |
| Listing `name`, `host_about` | mixed: not measured; names are written in pt, en, es, fr | inspection |
| Wikipedia articles | pt 772 of 788 (98 %); en 16 | `wikipedia_by_language.csv` |

Consequence: no single language analyzer fits the collection. Language has to be handled per field and, for
reviews, per document.

### 3.2 Decisions

| Field | Setup 1 | Setup 2 | Justification |
|---|---|---|---|
| `name`, `host_about` | `text_simple` | `text_multi` | mixed languages: a stemmer for one language damages the others. Setup 2 adds query-time synonyms (en, pt) |
| `description` | `text_simple` | `text_en_fold` | 99 % English: English stop words and stemming are safe |
| `comments_en` | – | `text_en_fold` | the approach is to search the reviews in English only. 57.3 % are already English; the six other main languages (fr, pt, es, de, it, nl: 39.6 %) are machine-translated to English (`make translate`) and indexed in the same field, so one analyzer with English stemming and synonyms serves 96.9 % of the reviews and a query in English finds what guests wrote in any of them. A review of those languages without a translation yet is skipped |
| (none) | – | – | the remaining 3.1 % (~75 k reviews, ~80 languages, none above 0.9 %) are **discarded**: they cannot be translated with the six models, no single analyzer would serve them, and they are too few to change the ranking |
| `poi_name`, `wikipedia_title` | – | `text_multi` | proper names, any language |
| `wikipedia_text` | – | `text_pt_fold` | 98 % Portuguese. The 16 English articles are stemmed with Portuguese rules; accepted, since the effect is a looser match, not a lost one |

Components of the `<base>_fold` types (`text_en_fold`, `text_pt_fold`, derived from Solr's own `text_en` and `text_pt` by `_derive`):
- **Accent folding** (`asciiFolding`) after the stop filter and before the stemmer: stop words are still
  recognised with their accents, and a missing or extra accent in the query stops mattering.
- **Stop words and stemming** are inherited from the Solr type of the language.
- **Synonyms** (managed resources `syn_<lang>`, query side only, so changing them needs no reindexing):
  quiet/peaceful/calm, apartment/flat, air conditioning/air conditioner/ac, metro/subway, elevator/lift for
  English (the list includes the variants the translations produce), and sossegado/tranquilo/calmo,
  apartamento/flat, ar condicionado/ac for Portuguese. They are inserted right after the first lowercase
  filter, so they are written with accents and applied before the stop filter. `text_multi` applies both
  lists.

Checked on the running cores:
- `comments_en`: "The apartment was very quiet" is indexed as `apart veri quiet`; the query "calm" expands to `calm peac quiet silent`, so it matches.
- `description:renovate` finds 348 listings in setup 2 (the same as `renovated`); setup 1 finds 0 for `renovate` and 331 for `renovated`.

## 4. The two setups

| | Setup 1 (`configs/setup1.json`, core `airbnb_s1`) | Setup 2 (`configs/setup2.json`, core `airbnb_s2`) |
|---|---|---|
| Document model | flat: listings only | listings + nested reviews + nested POIs |
| Searchable fields | `name`, `description`, `host_about` | those + `comments_en`, `poi_name`, `wikipedia_title`, `wikipedia_text` |
| Analysis | one simple type (`text_simple`: standard tokenizer, lowercase, ascii folding) | `text_en_fold` (description, reviews), `text_pt_fold` (Wikipedia), `text_multi`, synonyms |
| Listing text `qf` / `pf` | `name^3 description^2 host_about^0.5` / `name^6 description^4`, `ps=2`, `tie=0.1`, `mm=2<-1 5<50%` | same |
| Evidence from children | none | `{!parent}` score of reviews (`^0.5`, `score=avg`) and of POIs (`^0.3`, `score=max`), combined with OR so that a listing can be found through them |
| Quality boost | none | multiplicative `1 + 0.1·rating + 0.02·ln(1 + number_of_reviews)` (about 1.0–1.6) |
| Filters | identical (`scripts/queries/*.json`) | identical |

The setups share the data, the hard filters and the listing-text edismax parameters, and each query file is
the same for both (`scripts/solr_query.py query.json --setup configs/setup1.json configs/setup2.json`). The
difference in results therefore comes from three things, each with a reason:
1. **Nested reviews and POIs**: users ask about experience and surroundings, which only exist in the children. Cost: far more documents (in the 3,000-listing test below, 117,721 review and 88,919 POI children for 3,000 parents), and each of the 291,355 POI children with an article repeats its full Wikipedia text.
2. **Language-aware analysis**: 43 % of the reviews are not English, and with a simple analyzer plurals and verb forms never match. Translation to English plus English stemming and synonyms puts the reviews of the six translated languages in one searchable vocabulary.
3. **Boosts**: rating and popularity break ties between textually similar listings.

Limits of the comparison: setup 2 changes three factors at once, so it tells whether the whole is better, not
which factor helps. Each factor is a separate block of the config (`analysis`, `nested`, `query.params`), so an
ablation is a copy of the file with one block switched. Relevance is not evaluated here (it needs judgements).

Observed on the first 3,000 listings of `documents.jsonl`, indexed without the translations (they were not
generated yet, so reviews in fr, pt, es, de, it and nl are skipped and only the English reviews are
searched; a full run finds more):

| Query | Setup 1 | Setup 2 |
|---|---|---|
| `apartments_ribeira` ("apartamento", 500 m around Ribeira) | 9 results | 29 results. "Porto Ribeira Flat" is rank 3 although its name has no "apartamento": the pt synonym group apartamento = flat applies to `name` |
| `rural_quiet` ("sossegado tranquilo calmo quiet peaceful calm"; ≤ 20 POIs, ≥ 1 food place, rating ≥ 4.8, ≥ 5 reviews) | 0 results: the six terms rarely co-occur in the listing text and `mm` asks for 3 | 67 results, found through the reviews and the synonyms |

Setup 1 returning 0 is what a baseline should show here: the vocabulary gap that synonyms and review text
close. It is not evidence of precision; setup 2 trades some precision for that recall.

## 5. Example

A listing (parent) as indexed in setup 2 (abridged):

```json
{ "id": "listing_620462", "doc_type": "listing", "city": "porto",
  "name": "Porto Ribeira Moments - Apartamento com Elevador",
  "description": "PORTO RIBEIRA MOMENTS apartment (52 m2), signed by the Architect Tiago Torre, is located at Rua de São João ...",
  "room_type": "Entire home/apt", "price": 107.54, "review_scores_rating": 4.94, "number_of_reviews": 282,
  "location": "41.141308,-8.613262", "poi_count_500m": 504, "food_count_500m": 352,
  "reviews": [ { "id": "review_...", "doc_type": "review", "lang": "fr", "date": "2025-08-17T00:00:00Z",
                 "comments_en": "Excellent stay in the historic centre of Porto! The apartment is located very close to the ..." } ],
  "pois":    [ { "id": "listing_620462_node/...", "doc_type": "poi", "poi_name": "Taberna dos Mercadores",
                 "category": "food and drink", "type": "restaurant", "distance_m": 19.0 } ] }
```

(The real document has 261 reviews and 55 POIs.) How its text is analysed:

| Text | Field → type | Index tokens |
|---|---|---|
| "Porto Ribeira Moments - Apartamento com Elevador" | `name` → `text_multi` | `porto ribeira moments apartamento com elevador`; the query "apartamento" also looks for "flat" |
| "The apartment was very quiet" (a French review, translated) | `comments_en` → `text_en_fold` | `apart veri quiet` (stop words, folding, stemming); the query "calm" also looks for peaceful, quiet, silent |

`apartments_ribeira.json` (query "apartamento"; filters `doc_type:listing`, `city:porto`, `geofilt` 0.5 km around
41.1406,-8.6139) becomes, in setup 2, the OR of three scored parts: edismax over the listing text,
`{!parent}` over `comments_en`, and `{!parent}` over the POI fields. The filters apply to the
parent, so the result is always a listing. Ranks 1–3 are "OPO DOMUS - Porto's Historic Center", "Apartamento T1"
and "Porto Ribeira Flat" (setup 1: "OPO DOMUS - Porto's Historic Center", "Apartamento T1", "Porto Ribeira
Moments - Apartamento com Elevador").

## 6. Running

```
make solr-up      # docker compose: cores airbnb_s1 and airbnb_s2
make translate    # optional, about 10 hours: English text of the fr, pt, es, de, it, nl reviews
make index        # both setups; ARGS="--limit 3000" indexes only the first 3,000 listings
python scripts/solr_query.py scripts/queries/rural_quiet.json --setup configs/setup1.json configs/setup2.json
```
