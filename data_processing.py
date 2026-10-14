import pandas as pd
from pathlib import Path

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
CITIES = ["porto", "lisboa"]


MIN_REVIEW_LENGTH = 50
YEARS_ACTIVE = 3
MIN_REVIEWS = 1

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

def process_listings(df):
    print(f"Listings originais: {len(df)}")
    
    if 'price' in df.columns:
        df['price'] = df['price'].astype(str).str.replace(r'[\$,]', '', regex=True).astype(float)

    if 'last_review' in df.columns:
        df['last_review'] = pd.to_datetime(df['last_review'], errors='coerce')
        limit_date = pd.to_datetime('today') - pd.DateOffset(years=YEARS_ACTIVE)
        df = df[df['last_review'] >= limit_date]
    
    if 'number_of_reviews' in df.columns:
        df = df[df['number_of_reviews'] >= MIN_REVIEWS]

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
    print(f"💬 Reviews originais: {len(df)}")
    
    df = df[df['listing_id'].isin(valid_listing_ids)]
    
    df = df.dropna(subset=['comments'])
    
    df['comments'] = df['comments'].astype(str)
    df = df[df['comments'].str.len() >= MIN_REVIEW_LENGTH]

    print(f"Reviews processadas (pós-filtros): {len(df)}")
    return df

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("--- A iniciar o processamento de Alojamentos (Listings) ---")
    listings = load_and_combine("listings.csv.gz")
    
    if not listings.empty:
        listings_limpas = process_listings(listings)
        
        path_listings_out = PROCESSED_DIR / "listings_clean.csv"
        listings_limpas.to_csv(path_listings_out, index=False)
        
        print("\n--- A iniciar o processamento de Comentários (Reviews) ---")
        reviews = load_and_combine("reviews.csv.gz")
        
        if not reviews.empty:
            valid_ids = listings_limpas['id'].unique()
            reviews_limpas = process_reviews(reviews, valid_ids)
            path_reviews_out = PROCESSED_DIR / "reviews_clean.csv"
            reviews_limpas.to_csv(path_reviews_out, index=False)
    print(f"\nProcessamento concluído! Os ficheiros finais estão na pasta: {PROCESSED_DIR}")

if __name__ == "__main__":
    main()