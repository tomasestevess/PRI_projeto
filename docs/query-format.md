# Query files, filters and block joins

The in-scope topics are IN1, IN2, IN3 and IN5. Each topic has one JSON file per Solr setup:
`scripts/queries/inN.setup1.json` and `scripts/queries/inN.setup2.json`.

## JSON format

Every query JSON uses the same keys:

| Key | Meaning |
|---|---|
| `description` | Human-readable topic note; it is not sent as query text. |
| `query` | Topic title/query text sent to Solr. Keep it the same in both setup files for a topic. |
| `filter` | Array of Solr filter queries (`fq`). Every result must be a listing. Setup-specific child filters belong only in setup 2. |
| `fields` | Comma-separated Solr fields returned for display and run-file generation. Keep paired files consistent. |
| `limit` | Maximum number of results; use `100` for the TREC runs. |

The TREC query ID is derived from the filename: `in3.setup1.json` produces `IN3`. The run file uses the
six-column format `qid Q0 docid rank score runid`.

Example:

```json
{
  "description": "IN2: Family apartment in Lisbon for at least four guests.",
  "query": "family apartment close to the beach in Lisbon",
  "filter": [
    "doc_type:listing",
    "city:lisboa",
    "accommodates:[4 TO *]"
  ],
  "fields": "id,name,city,neighbourhood_cleansed,price,accommodates,review_scores_rating,listing_url,score",
  "limit": 100
}
```

## Common listing filters

Use these filters when a topic has the corresponding constraint. Combine them in the JSON `filter` array;
`doc_type:listing` keeps results at the listing level.

| Constraint | Solr filter example | Field |
|---|---|---|
| City | `city:porto` or `city:lisboa` | Exact city string |
| Price range | `price:[50 TO 120]` | Numeric nightly price range; `*` can stand for an open bound |
| Minimum capacity | `accommodates:[4 TO *]` | Minimum number of guests |

For example, a topic limited to Lisbon, nightly prices from 50 to 120, and at least four guests uses
`doc_type:listing`, `city:lisboa`, `price:[50 TO 120]` and `accommodates:[4 TO *]` as separate filters.
Do not add a price or capacity constraint unless it is part of the information need.

## Nested review and POI templates

Setup 2 stores each listing as a parent block with `review` and `poi` child documents. Setup 1 is flat and
cannot run these joins. In the snippets below, `$parents` is `doc_type:listing`; `$review_q` must match
review children and `$poi_q` must match POI children. The existing definitions are in
`configs/setup2.json` under `query.params`.

| Evidence | Return matching listings with `{!parent}` | Return matching child documents with `{!child}` |
|---|---|---|
| Reviews | `{!parent which=$parents score=avg v=$review_q}` | `{!child of=$parents v=$review_q}` |
| POIs | `{!parent which=$parents score=max v=$poi_q}` | `{!child of=$parents v=$poi_q}` |

The review query should target review fields, for example `comments_en`; the POI query should be constrained
to `doc_type:poi` and target fields such as `poi_name`, `wikipedia_title` or `wikipedia_text`. To require a
nearby POI as a hard filter on listing results, use a parent join such as:

```text
{!parent which=$parents v='doc_type:poi AND category:"leisure" AND distance_m:[0 TO 500] AND type:(beach OR beach_resort)'}
```

The reusable form is:

```text
{!parent which=$parents v='doc_type:poi AND category:"<category>" AND distance_m:[0 TO <meters>] AND type:<poi_type>'}
```

`{!parent}` returns the matching listing parents. `{!child}` returns child documents for matched parent
blocks, so use it when the caller needs review or POI documents themselves. Keep the top-level
`doc_type:listing` filter in query JSON files so TREC runs contain listing IDs.
