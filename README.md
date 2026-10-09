# PRI - Project

Search system for short-term rentals (Airbnb) in Porto and Lisbon.
It combines the Inside Airbnb listings and reviews with OpenStreetMap points of interest and Wikipedia articles about those places.

## Group

| Name           | Number | Email |
|----------------|--------|-------|
| Gonçalo Ferros | 202207592 | up202207592@up.pt |
| Inês Oliveira | 202305418 | up202305418@up.pt |
| Joana Carvalhal | 202306568 | up202306568@up.pt |
| Tomás Esteves | 202205045 | up202205045@up.pt |

## Setup
Requires make, bash, curl and python 3.9+. On Windows, install make with `winget install ezwinports.make` and run it from Git Bash.

```
pip install -r scripts/requirements.txt
make collect
```

**make collect**: downloads the raw data into data/raw/. It takes about 20 minutes, almost all of it fetching Wikipedia. If it is interrupted, run it again and it resumes.

## Structure
```
Makefile                        data pipeline (make collect downloads the raw data)
scripts/osm_query.overpass.in   Overpass query, @BBOX@ is replaced by each city's bounding box
scripts/fetch_wikipedia.py      fetches Wikipedia articles
data/raw/                       raw data
```

## Data
The raw data is not tracked by git.

### Sources

- data/raw/airbnb_porto and airbnb_lisboa: Inside Airbnb (https://insideairbnb.com/get-the-data/)
- data/raw/osm: OpenStreetMap via the Overpass API
- data/raw/wikipedia: Wikipedia

### Files

**Inside Airbnb**
- listings.csv.gz: listings, 90 columns (description, neighbourhood, coordinates, price...). Porto ~15k, Lisbon ~25k.
- reviews.csv.gz: listing_id, id, date, reviewer_id, reviewer_name, comments. Porto ~1,1M, Lisbon ~1,9M
- neighbourhoods.geojson: neighbourhood boundaries (coordinates).

**OpenStreetMap**
- pois_porto.json and pois_lisboa.json: Overpass response.
Categories:
  - food and drink
  - tourism and heritage
  - transport (stations, metro, bus stops)
  - shops (supermarkets, bakeries, convenience)
  - leisure (parks, beaches)
  - public parking

**Wikipedia**
- articles.jsonl: one article per line with qid, lang, title, text (usually the article body), url,
  revid and pois.
- Fetched with the Wikidata API and the Wikipedia TextExtracts
  API.
