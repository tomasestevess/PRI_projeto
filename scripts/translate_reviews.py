"""Translates the non-English reviews to English, so that all reviews are searched through comments_en.

Runs on the CPU with CTranslate2 and the Argos Translate models, downloaded to data/raw/models.
Writes data/processed/reviews_en.jsonl, one {"id", "text"} per review. It takes hours: if it is
interrupted, run it again and it resumes.

Usage: python scripts/translate_reviews.py [--langs fr pt] [--limit N]
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REVIEWS = Path("data/processed/reviews_clean.csv")
OUT = Path("data/processed/reviews_en.jsonl")
MODELS = Path("data/raw/models")
ARGOS = "https://argos-net.com/v1/translate-{}.argosmodel"
UA = "FEUP-PRI-student-project/0.1"  # the server answers 403 to urllib's default User-Agent
# es stays at 1.0: from 1.9 on it needs another tokenizer
MODEL_VERSIONS = {"fr": "fr_en-1_9", "es": "es_en-1_0", "pt": "pt_en-1_9", "de": "de_en-1_3",
                  "it": "it_en-1_0", "nl": "nl_en-1_8"}
CHUNK = 2000  # reviews between writes, which is what is lost if interrupted
SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def load_translations():
    """Translations made so far, by review id."""
    translations = {}
    if OUT.exists():
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:  # cut short by an interruption
                    continue
                translations[row["id"]] = row["text"]
    return translations


def load_pending(done, langs, limit):
    pending = {lang: [] for lang in langs}
    csv.field_size_limit(sys.maxsize if os.name != "nt" else 2**31 - 1)
    with open(REVIEWS, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            lang, review_id = row["lang"], f"review_{row['id']}"
            if lang in pending and review_id not in done and not (limit and len(pending[lang]) >= limit):
                pending[lang].append((review_id, row["comments"]))
    return pending


def model_dir(lang):
    """Downloads the model the first time. The archives have no common layout, hence the search for it."""
    path = MODELS / lang
    if not path.exists():
        MODELS.mkdir(parents=True, exist_ok=True)
        archive = MODELS / f"{lang}.zip"
        print(f"downloading the {lang} model", flush=True)
        request = urllib.request.Request(ARGOS.format(MODEL_VERSIONS[lang]), headers={"User-Agent": UA})
        with urllib.request.urlopen(request) as response, open(archive, "wb") as f:
            shutil.copyfileobj(response, f)
        tmp = MODELS / f"{lang}.tmp"
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        (root,) = (p.parent for p in tmp.rglob("metadata.json"))
        root.rename(path)
        shutil.rmtree(tmp, ignore_errors=True)
        archive.unlink()
    return path


def load_cpp_runtime():
    """ctranslate2 crashes on Windows machines whose System32 has an old MSVCP140.dll. scikit-learn ships
    a recent one, which is used if it is there: loading it first makes ctranslate2 use it too."""
    sklearn = importlib.util.find_spec("sklearn")
    if os.name == "nt" and sklearn:
        dll = Path(sklearn.origin).parent / ".libs" / "msvcp140.dll"
        if dll.exists():
            import ctypes
            ctypes.WinDLL(str(dll))


def translate(translator, tokenizer, texts, beam):
    """Translates sentence by sentence, as the models expect, and only once for sentences that repeat."""
    parts = [SENTENCE.split(text) for text in texts]
    unique = list({sentence for sentences in parts for sentence in sentences})
    tokens = [tokenizer.encode(sentence, out_type=str) for sentence in unique]
    results = translator.translate_batch(tokens, beam_size=beam, max_batch_size=32, repetition_penalty=1.1,
                                         max_decoding_length=256)
    english = {s: "".join(r.hypotheses[0]).replace("▁", " ").strip() for s, r in zip(unique, results)}
    return [" ".join(english[s] for s in sentences) for sentences in parts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", nargs="+", default=list(MODEL_VERSIONS), choices=list(MODEL_VERSIONS))
    ap.add_argument("--limit", type=int, help="reviews per language, for a quick test")
    ap.add_argument("--workers", type=int, default=4, help="batches translated in parallel")
    ap.add_argument("--threads", type=int, default=2, help="CPU threads per worker")
    ap.add_argument("--beam", type=int, default=1, help="1 is about twice as fast as 2")
    args = ap.parse_args()

    load_cpp_runtime()
    import ctranslate2
    import sentencepiece

    done = load_translations()
    print(f"{len(done)} already translated", flush=True)
    pending = load_pending(done, args.langs, args.limit)
    del done
    with open(OUT, "a", encoding="utf-8") as out:
        out.write("\n")  # after an interrupted line, if there is one
        for lang, reviews in pending.items():
            if not reviews:
                continue
            path = model_dir(lang)
            tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
            translator = ctranslate2.Translator(str(path / "model"), device="cpu", compute_type="int8",
                                                inter_threads=args.workers, intra_threads=args.threads)
            start = time.time()
            for i in range(0, len(reviews), CHUNK):
                chunk = reviews[i:i + CHUNK]
                english = translate(translator, tokenizer, [text for _, text in chunk], args.beam)
                out.write("".join(json.dumps({"id": review_id, "text": text}, ensure_ascii=False) + "\n"
                                  for (review_id, _), text in zip(chunk, english)))
                out.flush()
                finished = i + len(chunk)
                rate = finished / (time.time() - start)
                print(f"{lang}: {finished}/{len(reviews)} ({rate:.1f} reviews/s, "
                      f"{(len(reviews) - finished) / rate / 3600:.1f} h left)", flush=True)


if __name__ == "__main__":
    main()
