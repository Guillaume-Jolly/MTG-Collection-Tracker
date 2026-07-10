#!/usr/bin/env python3
"""Diagnostic verify_migration mismatch."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH, connect, init_db
from mtg_pwa.price_daily import (
    active_price_daily_columns,
    count_narrow_price_cells,
    verify_migration,
    PRICE_DAILY_VALUE_COLUMNS,
    EXCLUDED_SNAPSHOT_SOURCES,
)


def main() -> int:
    conn = connect(DEFAULT_DB_PATH)
    init_db(conn)

    obj = conn.execute(
        "SELECT type, sql FROM sqlite_master WHERE name='price_snapshots'"
    ).fetchone()
    print("price_snapshots object:", obj["type"] if obj else None)
    if obj and obj["sql"]:
        print("view sql preview:", obj["sql"][:200], "...")

    print("\n=== Legacy breakdown ===")
    queries = {
        "scryfall-cardmarket": "source = 'scryfall-cardmarket'",
        "USD mtgjson": "source IN ('mtgjson-cardkingdom','mtgjson-tcgplayer','mtgjson-manapool')",
        "mtgjson-cardmarket": "source = 'mtgjson-cardmarket'",
        "en-print": "source LIKE 'scryfall-cardmarket-en-print:%'",
        "narrow (verify filter)": """source NOT IN ('mtgjson-cardmarket')
          AND source NOT LIKE 'scryfall-cardmarket-en-print:%'""",
        "EUR active (scryfall only)": "source = 'scryfall-cardmarket'",
    }
    for label, where in queries.items():
        n = conn.execute(f"SELECT COUNT(*) FROM price_snapshots_legacy WHERE {where}").fetchone()[0]
        print(f"  {label}: {n:,}")

    print("\n=== price_daily column cells ===")
    for col in PRICE_DAILY_VALUE_COLUMNS:
        n = conn.execute(f"SELECT SUM(({col} IS NOT NULL)) FROM price_daily").fetchone()[0]
        print(f"  {col}: {int(n or 0):,}")

    print("\n=== Aggregates ===")
    print("  count_narrow_price_cells (EUR):", f"{count_narrow_price_cells(conn):,}")
    print("  view COUNT(*):", f"{conn.execute('SELECT COUNT(*) FROM price_snapshots').fetchone()[0]:,}")
    check = verify_migration(conn)
    print("  verify_migration:", check)

    # Extra: daily rows with any EUR vs any USD column
    eur_pred = " OR ".join(f"{c} IS NOT NULL" for c in active_price_daily_columns())
    usd_cols = [c for c in PRICE_DAILY_VALUE_COLUMNS if c not in active_price_daily_columns()]
    usd_pred = " OR ".join(f"{c} IS NOT NULL" for c in usd_cols)
    eur_rows = conn.execute(f"SELECT COUNT(*) FROM price_daily WHERE {eur_pred}").fetchone()[0]
    usd_rows = conn.execute(f"SELECT COUNT(*) FROM price_daily WHERE {usd_pred}").fetchone()[0]
    print(f"  daily rows with any EUR col: {eur_rows:,}")
    print(f"  daily rows with any USD col: {usd_rows:,}")

    # Post-migration writes: collected_at today but snapshot_date not today
    rows = conn.execute(
        """
        SELECT snapshot_date, COUNT(*) AS n
        FROM price_daily
        WHERE collected_at LIKE '2026-07-10%'
        GROUP BY snapshot_date
        ORDER BY n DESC
        LIMIT 10
        """
    ).fetchall()
    print("\n=== collected_at 2026-07-10 by snapshot_date ===")
    for row in rows:
        print(f"  {row['snapshot_date']}: {row['n']:,}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
