import pandas as pd
df = pd.DataFrame()
df = pd.read_csv("data/raw/airbnb_porto/listings.csv/listings.csv")
print("\nairbnb_porto\n")
print(100 * df.isna().mean().sort_values(ascending=False).loc[lambda s : s > 0].head(13))

df2 = pd.DataFrame()
df2 = pd.read_csv("data/raw/airbnb_porto/listings.csv/listings.csv")
print("\nairbnb_lisboa\n")
print(100 * df2.isna().mean().sort_values(ascending=False).loc[lambda s : s > 0].head(13))

df3 = pd.DataFrame()
df3 = pd.read_csv("data/processed/listings_clean.csv")
print("\nairbnb_clean\n")
print(100 * df3.isna().mean().sort_values(ascending=False).loc[lambda s : s > 0].head(13))
