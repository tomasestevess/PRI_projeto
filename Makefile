SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

RAW      := data/raw
UA       := FEUP-PRI-student-project/0.1
DATE     := 2026-06-23
PYTHON   := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(shell python3 --version >/dev/null 2>&1 && echo python3 || echo python))
CITIES   := porto lisboa
AIRBNB_porto  := portugal/norte/porto
AIRBNB_lisboa := portugal/lisbon/lisbon
BBOX_porto    := 40.76,-8.79,41.46,-8.10
BBOX_lisboa   := 38.67,-9.5,39.31,-8.85

AIRBNB := https://data.insideairbnb.com
FILES  := $(foreach c,$(CITIES),$(addprefix $(RAW)/airbnb_$(c)/,listings.csv.gz reviews.csv.gz neighbourhoods.geojson) $(RAW)/osm/pois_$(c).json) $(RAW)/wikipedia/articles.jsonl

# The all target helps automate the whole process: by running `make` from the command line, you can do everything in one go
# You can define further targets that only execute smaller subsets of your data pipeline according to your needs
# clean is left out so existing downloads are kept; run `make clean all` for a fresh start
all: collect process analyze

clean:
	rm -rf data processed analysis

.PHONY: all clean collect process analyze adhoc
# Downloads raw data to data/raw/. Files that already exist are skipped, so reruns resume.
collect: $(FILES)

# Downloads go to .part first so interrupted ones are not mistaken for complete files
$(RAW)/airbnb_%/listings.csv.gz:
	mkdir -p $(@D)
	curl -fL --retry 3 --retry-delay 10 -A "$(UA)" -o $@.part $(AIRBNB)/$(AIRBNB_$*)/$(DATE)/data/$(@F)
	mv $@.part $@

$(RAW)/airbnb_%/reviews.csv.gz:
	mkdir -p $(@D)
	curl -fL --retry 3 --retry-delay 10 -A "$(UA)" -o $@.part $(AIRBNB)/$(AIRBNB_$*)/$(DATE)/data/$(@F)
	mv $@.part $@

$(RAW)/airbnb_%/neighbourhoods.geojson:
	mkdir -p $(@D)
	curl -fL --retry 3 --retry-delay 10 -A "$(UA)" -o $@.part $(AIRBNB)/$(AIRBNB_$*)/$(DATE)/visualisations/$(@F)
	mv $@.part $@

# Overpass is rate limited: run without -j
$(RAW)/osm/pois_%.json: scripts/osm_query.overpass.in
	mkdir -p $(@D)
	sed 's/@BBOX@/$(BBOX_$*)/' $< | curl -sSf -m 600 --retry 5 --retry-delay 30 -A "$(UA)" --data-urlencode data@-		https://overpass-api.de/api/interpreter -o $@.part
	grep -q '"elements"' $@.part && ! grep -q 'runtime error' $@.part 		|| { rm -f $@.part; echo "Overpass returned no data; retry later" >&2; exit 1; }
	mv $@.part $@
	sleep 5

# ~15 minutes; needs the OSM POIs
$(RAW)/wikipedia/articles.jsonl: $(foreach c,$(CITIES),$(RAW)/osm/pois_$(c).json)
	$(PYTHON) -u scripts/fetch_wikipedia.py --raw $(RAW)

# Cleans the raw data and builds data/processed/documents.jsonl (listings with nested reviews and POIs)
process: data/processed/documents.jsonl

data/processed/documents.jsonl: data_processing.py $(FILES)
	$(PYTHON) data_processing.py --snapshot $(DATE)

analyze:
	find analysis/figures -type f -name '*.pdf' -delete
	$(PYTHON) -m jupyter nbconvert --to notebook --execute --inplace analysis/notebooks/01_eda.ipynb \
		--ExecutePreprocessor.timeout=600

adhoc:
	# This target is not part of the overall automation, but it can be useful to have something similar
	# to automate some less frequent operation that you might want to run only when strictly necessary
	# (e.g., organize all produced data/analysis and run a notebook for an easier visual verification of obtained results)
	# Rscript scripts/some_adhoc_script.R
