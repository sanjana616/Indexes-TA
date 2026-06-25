import sqlite3, pandas as pd

conn = sqlite3.connect('data/market_data.db')

print("=== NIFTY50 rows per date ===")
df = pd.read_sql_query("""
    SELECT substr(datetime,1,10) as date,
           COUNT(*) as candles,
           MIN(substr(datetime,12,5)) as first_time,
           MAX(substr(datetime,12,5)) as last_time
    FROM indexes
    WHERE stock_name='NIFTY50'
    GROUP BY date
    ORDER BY date DESC
""", conn)
print(df.to_string(index=False))

conn.close()
