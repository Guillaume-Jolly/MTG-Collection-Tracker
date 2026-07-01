from __future__ import annotations

from mtg_pwa.database import catalog_table, connect, init_db
from mtg_pwa.sets_catalog import market_eligible_set_codes
from mtg_pwa.server import market_mover_candidate_rows, snapshot_period_bounds

conn = connect()
init_db(conn)
eligible = sorted(market_eligible_set_codes())
cards = catalog_table("cards")
snap = catalog_table("price_snapshots")
ph = ",".join("?" for _ in eligible)

in_db = conn.execute(
    f"SELECT COUNT(*) FROM {cards} WHERE upper(set_code) IN ({ph})",
    tuple(eligible),
).fetchone()[0]

priced_eligible = conn.execute(
    f"""
    SELECT COUNT(DISTINCT ps.scryfall_id)
    FROM {snap} ps
    JOIN {cards} c ON c.scryfall_id = ps.scryfall_id
    WHERE upper(c.set_code) IN ({ph})
      AND ps.source IN ('mtgjson-cardmarket', 'scryfall-cardmarket')
      AND ps.finish = 'nonfoil'
    """,
    tuple(eligible),
).fetchone()[0]

bounds = snapshot_period_bounds(conn, "cardmarket", "7d")
if bounds:
    start, end = bounds
    candidates = market_mover_candidate_rows(conn, "cardmarket", start, end, eligible_set_codes=frozenset(eligible))
    print(f"market 7d candidates: {len(candidates)} ({start} -> {end})")
else:
    print("market 7d: no bounds")

row = conn.execute(f"SELECT MIN(snapshot_date), MAX(snapshot_date), COUNT(*) FROM {snap}").fetchone()
print(f"snapshots: {row[0]} .. {row[1]} ({row[2]} rows)")
print(f"eligible sets: {len(eligible)}")
print(f"cards in DB (eligible sets): {in_db}")
print(f"cards with any cardmarket snapshot (eligible, nonfoil): {priced_eligible}")
conn.close()
