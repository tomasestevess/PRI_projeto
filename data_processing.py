import argparse
import html
import json
import math
import os
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Antes de importar o numpy: cada worker da deteção de língua reservaria buffers para todas as threads e esgotava a memória
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import py3langid
from scipy.spatial import cKDTree

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
CITIES = ["porto", "lisboa"]


MIN_REVIEW_LENGTH = 50
YEARS_ACTIVE = 3
MIN_REVIEWS = 1
POI_RADIUS_M = 500
MAX_POIS_PER_CATEGORY = 5  # POIs mais próximos por categoria; os que têm artigo da Wikipedia entram sempre
LANG_WORKERS = min(6, os.cpu_count() or 1)  # cada worker carrega o pandas e o modelo de língua
EARTH_RADIUS_M = 6_371_000

# (tag, valores, categoria), pela mesma ordem que osm_category no notebook de EDA
POI_TYPES = [
    ("highway", {"bus_stop"}, "transport"),
    ("station", {"subway"}, "transport"),
    ("railway", {"station"}, "transport"),
    ("amenity", {"restaurant", "cafe", "bar", "pub", "fast_food", "ice_cream"}, "food and drink"),
    ("tourism", {"attraction", "museum", "viewpoint", "gallery"}, "tourism and heritage"),
    ("historic", {"monument", "castle", "church", "memorial"}, "tourism and heritage"),
    ("shop", {"supermarket", "bakery", "convenience"}, "shops"),
    ("leisure", {"park", "beach_resort"}, "leisure"),
    ("natural", {"beach"}, "leisure"),
    ("amenity", {"parking"}, "public parking"),
]

# Secções finais dos artigos; as inglesas cobrem os artigos obtidos em inglês como fallback
WIKI_END_SECTIONS = re.compile(
    r"^==\s*(Referências|Ligações externas|Ver também|Bibliografia"
    r"|References|External links|See also|Bibliography)\s*==\s*$",
    re.MULTILINE | re.IGNORECASE,
)

def load_and_combine(filename):
    """Lê um ficheiro específico de ambas as cidades e junta-os num só DataFrame."""
    dfs = []
    for city in CITIES:
        path = RAW_DIR / f"airbnb_{city}" / filename
        if path.exists():
            df = pd.read_csv(path, compression='gzip', low_memory=False)
            df['city'] = city
            dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def clean_html(series):
    """Remove tags (<br />) e entidades HTML (&amp;) e normaliza os espaços; texto vazio passa a nulo."""
    text = series.astype("string").str.replace(r"</?[a-zA-Z][^>]*>", " ", regex=True)
    text = text.map(html.unescape, na_action="ignore").astype("string")
    return text.str.replace(r"\s+", " ", regex=True).str.strip().replace("", pd.NA)

def detect_lang(texts):
    return [py3langid.classify(text)[0] for text in texts]

def detect_languages(texts, chunk_size=20000):
    """Deteta a língua de cada texto (códigos ISO 639-1), em paralelo porque são milhões de reviews."""
    chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
    with ProcessPoolExecutor(max_workers=LANG_WORKERS) as executor:
        return [lang for chunk in executor.map(detect_lang, chunks) for lang in chunk]

def process_listings(df, snapshot):
    print(f"Listings originais: {len(df)}")

    if 'price' in df.columns:
        df['price'] = df['price'].astype(str).str.replace(r'[\$,]', '', regex=True).astype(float)

    if 'last_review' in df.columns:
        df['last_review'] = pd.to_datetime(df['last_review'], errors='coerce')
        limit_date = snapshot - pd.DateOffset(years=YEARS_ACTIVE)
        df = df[df['last_review'] >= limit_date]

    if 'number_of_reviews' in df.columns:
        df = df[df['number_of_reviews'] >= MIN_REVIEWS]

    for col in ['name', 'description', 'host_about']:
        df[col] = clean_html(df[col])

    df['amenities'] = df['amenities'].map(json.loads, na_action='ignore')

    colunas_obrigatorias = [
        'name', 'description', 'latitude', 'longitude',
        'neighbourhood_cleansed', 'price', 'accommodates',
        'room_type', 'property_type', 'number_of_reviews',
        'review_scores_rating'
    ]

    colunas_presentes = [col for col in colunas_obrigatorias if col in df.columns]
    df = df.dropna(subset=colunas_presentes)

    colunas_lixo = [
        'neighbourhood', 'instant_bookable', 'host_acceptance_rate',
        'host_response_rate', 'host_response_time', 'host_since', 'host_total_listings_count',
        'host_verifications', 'host_since', 'host_neighbourhood', 'host_thumbnail_url',
        'neighborhood_overview', 'calendar_updated'
    ]

    df = df.drop(columns=colunas_lixo)

    print(f"Listings processadas (pós-filtros): {len(df)}")
    return df

def process_reviews(df, valid_listing_ids):
    print(f"Reviews originais: {len(df)}")

    df = df[df['listing_id'].isin(valid_listing_ids)]

    df = df.assign(comments=clean_html(df['comments']))
    df = df.dropna(subset=['comments'])

    df = df[df['comments'].str.len() >= MIN_REVIEW_LENGTH]

    df = df.assign(lang=detect_languages(df['comments'].tolist()))

    print(f"Reviews processadas (pós-filtros): {len(df)}")
    print(f"Línguas mais frequentes: {df['lang'].value_counts().head(5).to_dict()}")
    return df

def classify_poi(tags):
    for key, values, category in POI_TYPES:
        if tags.get(key) in values:
            return category, tags[key]
    return "other", None

def load_pois():
    """POIs do OSM com nome e coordenadas (centro, no caso de ways e relations)."""
    rows = []
    for city in CITIES:
        path = RAW_DIR / "osm" / f"pois_{city}.json"
        for e in json.loads(path.read_text(encoding="utf-8"))["elements"]:
            tags = e.get("tags", {})
            point = e if "lat" in e else e.get("center", {})
            name = tags.get("name", "").strip()
            if "lat" not in point or not name:  # sem nome não servem como documento
                continue
            category, poi_type = classify_poi(tags)
            rows.append({
                "osm_id": f"{e['type']}/{e['id']}", "city": city, "name": name,
                "category": category, "type": poi_type,
                "latitude": point["lat"], "longitude": point["lon"],
            })
    pois = pd.DataFrame(rows)
    print(f"POIs com nome: {len(pois)}")
    return pois

def strip_end_sections(text):
    match = WIKI_END_SECTIONS.search(text)
    return text[:match.start()].rstrip() if match else text

def load_wikipedia():
    path = RAW_DIR / "wikipedia" / "articles.jsonl"
    with open(path, encoding="utf-8") as f:
        articles = [json.loads(line) for line in f if line.strip()]
    print(f"Artigos originais: {len(articles)}")
    for article in articles:
        article["text"] = strip_end_sections(article["text"])
    return articles

def to_xyz(lat, lon):
    """Coordenadas cartesianas em metros; até 500 m a distância em linha reta coincide com a da superfície."""
    lat, lon = np.radians(lat), np.radians(lon)
    return EARTH_RADIUS_M * np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])

def link_pois(listings, pois):
    """Associa cada listing aos POIs num raio de POI_RADIUS_M (associação Proximity do modelo conceptual)."""
    listing_tree = cKDTree(to_xyz(listings['latitude'].to_numpy(), listings['longitude'].to_numpy()))
    poi_tree = cKDTree(to_xyz(pois['latitude'].to_numpy(), pois['longitude'].to_numpy()))
    pairs = listing_tree.sparse_distance_matrix(poi_tree, POI_RADIUS_M, output_type="ndarray")

    proximity = pd.DataFrame({
        "listing_id": listings['id'].to_numpy()[pairs["i"]],
        "poi": pairs["j"],
        "distance_m": pairs["v"].round(1),
        "category": pois['category'].to_numpy()[pairs["j"]],
    }).sort_values(["listing_id", "distance_m"])

    rank = proximity.groupby(["listing_id", "category"]).cumcount()
    has_article = pois['wikipedia_title'].notna().to_numpy()[proximity["poi"]]
    proximity = proximity[(rank < MAX_POIS_PER_CATEGORY) | has_article].drop(columns="category")
    print(f"Ligações listing-POI: {len(proximity)}")
    return proximity

def is_missing(value):
    return value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))

def records(df):
    """Linhas como dicionários sem campos em falta, que o Solr dispensa."""
    return [{k: v for k, v in row.items() if not is_missing(v)} for row in df.to_dict("records")]

def build_documents(listings, reviews, pois, proximity, path):
    """Um documento por listing, com as reviews e os POIs próximos como documentos aninhados do Solr."""
    reviews = reviews.assign(id="review_" + reviews['id'].astype(str), doc_type="review")
    review_docs = {
        listing_id: records(group.drop(columns=['listing_id', 'city']))
        for listing_id, group in reviews.groupby('listing_id')
    }

    nearby = proximity.join(pois.drop(columns=['city', 'latitude', 'longitude']), on="poi")
    nearby = nearby.assign(id="listing_" + nearby['listing_id'].astype(str) + "_" + nearby['osm_id'], doc_type="poi")
    poi_docs = {
        listing_id: records(group.drop(columns=['listing_id', 'poi']))
        for listing_id, group in nearby.groupby('listing_id')
    }

    listings = listings.assign(last_review=listings['last_review'].dt.strftime("%Y-%m-%d"))
    with open(path, "w", encoding="utf-8") as f:
        for listing in records(listings):
            listing_id = listing.pop('id')
            doc = {
                "id": f"listing_{listing_id}", "doc_type": "listing", "listing_id": listing_id, **listing,
                "reviews": review_docs.get(listing_id, []),
                "pois": poi_docs.get(listing_id, []),
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, help="data do snapshot do Inside Airbnb (DATE no Makefile)")
    snapshot = pd.Timestamp(parser.parse_args().snapshot)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("--- A iniciar o processamento de Alojamentos (Listings) ---")
    listings = process_listings(load_and_combine("listings.csv.gz"), snapshot)
    listings.assign(amenities=listings['amenities'].map(lambda a: json.dumps(a, ensure_ascii=False))) \
        .to_csv(PROCESSED_DIR / "listings_clean.csv", index=False)

    print("\n--- A iniciar o processamento de Comentários (Reviews) ---")
    reviews = process_reviews(load_and_combine("reviews.csv.gz"), listings['id'].unique())
    reviews.to_csv(PROCESSED_DIR / "reviews_clean.csv", index=False)

    print("\n--- A iniciar o processamento de Artigos (Wikipedia) ---")
    articles = load_wikipedia()
    with open(PROCESSED_DIR / "wikipedia_clean.jsonl", "w", encoding="utf-8") as f:
        for article in articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")

    print("\n--- A iniciar o processamento de Pontos de Interesse (OSM) ---")
    pois = load_pois()
    article_by_poi = {}
    for article in articles:
        for poi in article["pois"]:
            article_by_poi.setdefault(poi["osm"], article)
    for field in ["title", "url", "text"]:
        pois[f"wikipedia_{field}"] = pois['osm_id'].map(lambda osm_id: article_by_poi.get(osm_id, {}).get(field))
    pois.to_csv(PROCESSED_DIR / "pois_clean.csv", index=False)

    print("\n--- A ligar Listings a POIs ---")
    proximity = link_pois(listings, pois)
    proximity.assign(osm_id=pois['osm_id'].to_numpy()[proximity['poi']]).drop(columns="poi") \
        .to_csv(PROCESSED_DIR / "proximity.csv", index=False)

    print("\n--- A gerar os documentos ---")
    build_documents(listings, reviews, pois, proximity, PROCESSED_DIR / "documents.jsonl")
    print(f"\nProcessamento concluído! Os ficheiros finais estão na pasta: {PROCESSED_DIR}")

if __name__ == "__main__":
    main()
