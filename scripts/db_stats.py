from mtg_pwa.database import connect, init_db, catalog_table
from pathlib import Path

conn = connect()
init_db(conn)
db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
size_gb = db_path.stat().st_size / (1024**3) if db_path.exists() else 0
print("DB path:", db_path)
print("Size GB:", round(size_gb, 2))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for (t,) in tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        print(f"{t}: {n:,} rows")
    except Exception as e:
        print(f"{t}: error {e}")
ps = catalog_table("price_snapshots")
dates = conn.execute(
    f"SELECT snapshot_date, COUNT(*) c FROM {ps} GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 8"
).fetchall()
print("price_snapshots dates:", [(d[0], d[1]) for d in dates])
g = catalog_table("cardmarket_price_guide_daily")
dates2 = conn.execute(
    f"SELECT snapshot_date, COUNT(*) c FROM {g} GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 5"
).fetchall()
print("cm guide dates:", [(d[0], d[1]) for d in dates2])
conn.close()
