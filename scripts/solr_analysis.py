"""Text analysis for the `airbnb` core: accent folding and query-time synonyms.

For every language in REVIEW_LANGS a `<type>_fold` field type is derived from Solr's own type
(text_en -> text_en_fold), with the same filters plus:
  - a managed synonym filter right after the first lowercase filter (query side only)
  - asciiFolding right after the stop filter, before the stemmer, so stop words keep matching
`text_multi` is the simple type for listing texts, which are in mixed languages: no stemming.

Synonyms are stored in managed resources (one per language), loaded with SYNONYMS below.
"""
import json
import urllib.parse
import urllib.request

FOLD = {"name": "asciiFolding"}
# Terms in one list are equivalent to each other. Reviews are all in English; pt is for the listing texts.
# The English lists include the variants that the translations produce (air conditioner, subway, elevator).
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
MULTI_SYNONYMS = ["en", "pt"]  # applied to the mixed-language listing texts


def _call(url, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=600).read())


def _syn(lang):
    return {"class": "solr.ManagedSynonymGraphFilterFactory", "managed": f"syn_{lang}"}


def _derive(base, lang):
    """Builds the index and query analyzers of `<base>_fold` from the analyzer of `base`."""
    t = _call_get_type(base)
    src = t.get("indexAnalyzer") or t["analyzer"]
    filters = [f for f in src["filters"] if f.get("name") != "synonymGraph"]  # text_en ships a no-op one
    names = [f.get("name") for f in filters]
    filters.insert(names.index("stop") + 1, FOLD)
    index = {"tokenizer": src["tokenizer"], "filters": filters}
    query_filters = list(filters)
    if lang in SYNONYMS:
        query_filters.insert([f.get("name") for f in query_filters].index("lowercase") + 1, _syn(lang))
    return index, {"tokenizer": src["tokenizer"], "filters": query_filters}


def _call_get_type(name):
    return _call(f"{_solr}/schema/fieldtypes/{name}")["fieldType"]


def _put_type(ftype):
    exists = any(t["name"] == ftype["name"] for t in _call(f"{_solr}/schema/fieldtypes")["fieldTypes"])
    cmd = "replace-field-type" if exists else "add-field-type"
    r = _call(f"{_solr}/schema", {cmd: ftype})
    assert "errors" not in r, r


def define_analysis(solr, review_langs):
    global _solr
    _solr = solr
    for lang, base in review_langs.items():
        index, query = _derive(base, lang)
        _put_type({"name": f"{base}_fold", "class": "solr.TextField", "positionIncrementGap": "100",
                   "indexAnalyzer": index, "queryAnalyzer": query})
    multi_index = {"tokenizer": {"name": "standard"}, "filters": [{"name": "lowercase"}, FOLD]}
    multi_query = {"tokenizer": {"name": "standard"},
                   "filters": [{"name": "lowercase"}] + [_syn(l) for l in MULTI_SYNONYMS] + [FOLD]}
    _put_type({"name": "text_multi", "class": "solr.TextField", "positionIncrementGap": "100",
               "indexAnalyzer": multi_index, "queryAnalyzer": multi_query})
    load_synonyms(solr)


def load_synonyms(solr):
    """Fills the managed synonym resources, then reloads the core, as Solr only applies them on reload."""
    for lang, groups in SYNONYMS.items():
        for terms in groups:
            _call(f"{solr}/schema/analysis/synonyms/{lang_resource(lang)}", terms, method="PUT")
    core = solr.rstrip("/").rsplit("/", 1)[1]
    root = solr.rstrip("/").rsplit("/", 1)[0]
    _call(f"{root}/admin/cores?action=RELOAD&core={urllib.parse.quote(core)}")


def lang_resource(lang):
    return f"syn_{lang}"
