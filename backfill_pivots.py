import sqlite3

conn = sqlite3.connect("data/market_data.db")
cur = conn.cursor()

# All (symbol, date) pairs with NULL pivots
cur.execute("SELECT DISTINCT stock_name, substr(datetime,1,10) FROM indexes WHERE pivot IS NULL")
nulls = cur.fetchall()
print(f"NULL pivot (symbol, date) pairs: {len(nulls)}")

updated = 0
skipped = []
for symbol, date in nulls:
    row = cur.execute("""
        SELECT MAX(high), MIN(low)
        FROM indexes
        WHERE stock_name=? AND substr(datetime,1,10)=(
            SELECT MAX(substr(datetime,1,10)) FROM indexes
            WHERE stock_name=? AND substr(datetime,1,10)<?)
    """, (symbol, symbol, date)).fetchone()

    last_close = cur.execute("""
        SELECT close FROM indexes
        WHERE stock_name=? AND substr(datetime,1,10)=(
            SELECT MAX(substr(datetime,1,10)) FROM indexes
            WHERE stock_name=? AND substr(datetime,1,10)<?)
        ORDER BY datetime DESC LIMIT 1
    """, (symbol, symbol, date)).fetchone()

    if not row or row[0] is None or not last_close:
        skipped.append((symbol, date))
        continue

    ph, pl, pc = row[0], row[1], last_close[0]
    pivot    = (ph + pl + pc) / 3
    pivot_r1 = 2*pivot - pl
    pivot_r2 = pivot + (ph - pl)
    pivot_r3 = ph + 2*(pivot - pl)
    pivot_s1 = 2*pivot - ph
    pivot_s2 = pivot - (ph - pl)
    pivot_s3 = pl - 2*(ph - pivot)

    cur.execute("""
        UPDATE indexes SET pivot=?,pivot_r1=?,pivot_r2=?,pivot_r3=?,
        pivot_s1=?,pivot_s2=?,pivot_s3=?
        WHERE stock_name=? AND substr(datetime,1,10)=? AND pivot IS NULL
    """, (pivot,pivot_r1,pivot_r2,pivot_r3,pivot_s1,pivot_s2,pivot_s3,symbol,date))
    updated += cur.rowcount

conn.commit()
print(f"Updated : {updated} rows")
print(f"Skipped (no prev day in DB): {skipped}")

cur.execute("SELECT stock_name, substr(datetime,1,10), COUNT(*) FROM indexes WHERE pivot IS NULL GROUP BY 1,2 ORDER BY 2 DESC,1")
remaining = cur.fetchall()
print(f"Remaining NULL rows: {remaining if remaining else 'None — all clear'}")
conn.close()
