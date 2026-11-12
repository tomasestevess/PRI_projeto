"""Text analysis for a Solr core: the field types of a setup (configs/setupN.json, key "analysis") and the
query-time synonyms (key "synonyms").

Each entry of "analysis" has a `name` and a `kind`:
  simple   standard tokenizer, lowercase, asciiFolding. No stemming, stop words or synonyms. (Setup 1)
  multi    for text of mixed languages: like simple, plus the synonyms of the languages in `synonyms`
           (query side only). No stemming, as one stemmer would damage the other languages.
  derived  `<base>_fold`, built from Solr's own type `base` (text_en, text_pt...): the same tokenizer and
           filters, plus asciiFolding right after the stop filter (before the stemmer, so stop words keep
           matching) and, for the query side, the synonyms of `lang` right after the first lowercase filter
           (before the stop filter, so synonyms are written with their accents).

Synonyms are stored in managed resources (one per language, `syn_<lang>`), loaded from SYNONYMS below.
"""
import json
import urllib.parse
import urllib.request

FOLD = {"name": "asciiFolding"}
# Terms in one list are equivalent to each other. Reviews are searched in English (the other languages are
# translated), so English has the longest list, with the variants that the translations produce (air conditioner,
# subway, elevator); pt is for the Portuguese listing texts and the Wikipedia articles.
SYNONYMS = {
    "en": [["air conditioning", "air conditioner", "ac", "aircon"], ["apartment", "flat"],
           ["quiet", "peaceful", "calm", "silent"], ["dirty", "filthy", "unclean"],
           ["broken", "faulty", "malfunctioning"], ["breakfast", "brunch"], ["noisy", "loud"],
           ["wifi", "internet"], ["metro", "subway"], ["elevator", "lift"]],
    "pt": [["ar condicionado", "ac", "climatização"], ["apartamento", "flat"],
           ["sossegado", "tranquilo", "silencioso", "calmo"], ["sujo", "imundo"],
           ["avariado", "estragado", "partido", "avariada", "estragada"],
           ["pequeno almoço", "pequeno-almoço", "pequeno almoco"], ["barulhento", "ruidoso"]],
}


def _call(url, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=600).read())


def _syn(lang):
    return {"class": "solr.ManagedSynonymGraphFilterFactory", "managed": lang_resource(lang)}


def _filter_names(filters):
    return [f.get("name") for f in filters]


def _simple(spec):
    analyzer = {"tokenizer": {"name": "standard"}, "filters": [{"name": "lowercase"}, FOLD]}
    return analyzer, analyzer


def _multi(spec):
    index = {"tokenizer": {"name": "standard"}, "filters": [{"name": "lowercase"}, FOLD]}
    query = {"tokenizer": {"name": "standard"},
             "filters": [{"name": "lowercase"}] + [_syn(l) for l in spec.get("synonyms", [])] + [FOLD]}
    return index, query


def _derived(spec):
    t = _call(f"{_solr}/schema/fieldtypes/{spec['base']}")["fieldType"]
    src = t.get("indexAnalyzer") or t["analyzer"]
    filters = [f for f in src["filters"] if f.get("name") != "synonymGraph"]  # text_en ships a no-op one
    filters.insert(_filter_names(filters).index("stop") + 1, FOLD)
    query_filters = list(filters)
    if spec.get("synonyms"):
        query_filters.insert(_filter_names(query_filters).index("lowercase") + 1, _syn(spec["synonyms"]))
    return ({"tokenizer": src["tokenizer"], "filters": filters},
            {"tokenizer": src["tokenizer"], "filters": query_filters})


KINDS = {"simple": _simple, "multi": _multi, "derived": _derived}


def _put_type(ftype):
    exists = any(t["name"] == ftype["name"] for t in _call(f"{_solr}/schema/fieldtypes")["fieldTypes"])
    cmd = "replace-field-type" if exists else "add-field-type"
    r = _call(f"{_solr}/schema", {cmd: ftype})
    assert "errors" not in r, r


def define_analysis(solr, analysis, synonym_langs):
    global _solr
    _solr = solr
    for spec in analysis:
        index, query = KINDS[spec["kind"]](spec)
        _put_type({"name": spec["name"], "class": "solr.TextField", "positionIncrementGap": "100",
                   "indexAnalyzer": index, "queryAnalyzer": query})
    if synonym_langs:
        load_synonyms(solr, synonym_langs)


def load_synonyms(solr, langs):
    """Fills the managed synonym resources, then reloads the core, as Solr only applies them on reload."""
    for lang in langs:
        for terms in SYNONYMS[lang]:
            _call(f"{solr}/schema/analysis/synonyms/{lang_resource(lang)}", terms, method="PUT")
    core = solr.rstrip("/").rsplit("/", 1)[1]
    root = solr.rstrip("/").rsplit("/", 1)[0]
    _call(f"{root}/admin/cores?action=RELOAD&core={urllib.parse.quote(core)}")


def lang_resource(lang):
    return f"syn_{lang}"
