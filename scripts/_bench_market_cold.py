import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import connect, init_db
from mtg_pwa.server import HistoryBuildOptions, invalidate_market_movers_cache, market_price_movers

conn = connect()
init_db(conn)
conn.execute("DELETE FROM app_metadata WHERE key LIKE 'market_movers_cache:%'")
conn.commit()
invalidate_market_movers_cache()
opts = HistoryBuildOptions(market_scope="all", exclude_illiquid=True)
t0 = time.perf_counter()
market_price_movers(conn, "cardmarket", opts, "7d")
print("cold_ms", round((time.perf_counter() - t0) * 1000, 1))
conn.close()
