#!/usr/bin/env bash

# Downloads raw data to data/raw/ (rerun to resume). Usage: ./get_data.sh

set -euo pipefail
cd "$(dirname "$0")"

RAW=data/raw
UA="FEUP-PRI-student-project/0.1"

PYTHON=python3
python3 --version >/dev/null 2>&1 || PYTHON=python

# download <url> <file>
download() {
    [[ -s $2 ]] && return
    echo "$2"
    mkdir -p "$(dirname "$2")"
    curl -fL --retry 3 --retry-delay 10 -A "$UA" -o "$2.part" "$1"
    mv "$2.part" "$2"
}

# airbnb <city> <insideairbnb.com path>
airbnb() {
    local base="https://data.insideairbnb.com/$2/2026-06-23"
    for f in data/listings.csv.gz data/reviews.csv.gz visualisations/neighbourhoods.geojson; do
        download "$base/$f" "$RAW/airbnb_$1/$(basename "$f")"
    done
}

# osm <city> <bbox south,west,north,east>
osm() {
    local query="$RAW/osm/query_$1.overpass" out="$RAW/osm/pois_$1.json" b=$2
    mkdir -p "$RAW/osm"
    cat > "$query" <<EOF
[out:json][timeout:300];
(
  nwr["amenity"~"^(restaurant|cafe|bar|pub|fast_food|ice_cream)$"]($b);
  nwr["tourism"~"^(attraction|museum|viewpoint|gallery)$"]($b);
  nwr["historic"~"^(monument|castle|church|memorial)$"]($b);
  nwr["railway"="station"]($b);
  nwr["station"="subway"]($b);
  nwr["shop"~"^(supermarket|bakery|convenience)$"]($b);
  nwr["leisure"~"^(park|beach_resort)$"]["name"]($b);
  nwr["natural"="beach"]["name"]($b);
  nwr["amenity"="parking"]["access"!="private"]($b);
  nwr["highway"="bus_stop"]($b);
);
out center tags;
EOF
    [[ -s $out ]] && return
    echo "$out"

    curl -sf -m 600 --retry 5 --retry-delay 30 -A "$UA" --data-urlencode "data@$query" \
        https://overpass-api.de/api/interpreter -o "$out.part"
    grep -q '"elements"' "$out.part" && ! grep -q 'runtime error' "$out.part"         || { rm -f "$out.part"; echo "Overpass returned no data; retry later" >&2; exit 1; }
    mv "$out.part" "$out"
}

airbnb porto portugal/norte/porto
airbnb lisboa portugal/lisbon/lisbon

osm porto "40.76,-8.79,41.46,-8.10"
sleep 5  # due to rate limiting
osm lisboa "38.67,-9.5,39.31,-8.85"

"$PYTHON" -u scripts/fetch_wikipedia.py  # ~15 minutes
