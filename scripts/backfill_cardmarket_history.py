"""Backfill cardmarket_price_guide_daily from local MTGJSON price cache."""
from __future__ import annotations

import argparse

from mtg_pwa.cardmarket_backfill import backfill_guide_from_mtgjson_cache
from mtg_pwa.cardmarket_export import refresh_cardmarket_product_map
from mtg_pwa.database import connect, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Cardmarket guide history from mtgjson_price_cache.")
    parser.add_argument("--limit", type=int, default=None, help="Limit UUID rows processed.")
    parser.add_argument("--skip-map", action="store_true", help="Skip product map refresh.")
    args = parser.parse_args()
    conn = connect()
    init_db(conn)
    if not args.skip_map:
        refresh_cardmarket_product_map(conn)
    result = backfill_guide_from_mtgjson_cache(conn, limit_uuids=args.limit)
    conn.close()
    print(
        f"Termine: {result.get('rows_written', 0)} lignes guide, "
        f"{result.get('cards_processed', 0)} cartes."
    )


if __name__ == "__main__":
    main()
