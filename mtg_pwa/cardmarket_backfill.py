from __future__ import annotations

import json
import sqlite3
from typing import Any

from .database import (
    cardmarket_product_id_by_scryfall,
    catalog_table,
    save_cardmarket_price_guide_daily,
    utc_now,
)

WRITE_BATCH_SIZE = 400


def _retail_prices(entry: dict[str, Any], finish_key: str) -> dict[str, float]:
    prices = (
        (((entry.get("paper") or {}).get("cardmarket") or {}).get("retail") or {}).get(finish_key) or {}
    )
    parsed: dict[str, float] = {}
    for snapshot_date, raw in prices.items():
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            parsed[str(snapshot_date)] = value
    return parsed


def backfill_guide_from_mtgjson_cache(
    conn: sqlite3.Connection,
    *,
    limit_uuids: int | None = None,
    on_log: Any = None,
) -> dict[str, int]:
    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)
        else:
            print(message, flush=True)

    map_table = catalog_table("mtgjson_card_map")
    cache_table = catalog_table("mtgjson_price_cache")
    sql = f"""
        SELECT m.scryfall_id, m.mtgjson_uuid, c.raw_json
        FROM {map_table} m
        INNER JOIN {cache_table} c ON c.mtgjson_uuid = m.mtgjson_uuid
        ORDER BY m.scryfall_id
    """
    if limit_uuids is not None:
        sql += f" LIMIT {int(limit_uuids)}"
    rows = conn.execute(sql).fetchall()
    if not rows:
        log("Aucune entree mtgjson_price_cache a backfiller.")
        return {"cards_processed": 0, "rows_written": 0}

    product_by_scryfall = cardmarket_product_id_by_scryfall(conn, [row["scryfall_id"] for row in rows])
    collected_at = utc_now()
    pending: list[dict[str, Any]] = []
    rows_written = 0
    cards_processed = 0

    def flush() -> None:
        nonlocal rows_written, pending
        if not pending:
            return
        rows_written += save_cardmarket_price_guide_daily(conn, pending)
        conn.commit()
        pending = []

    for row in rows:
        scryfall_id = row["scryfall_id"]
        id_product = product_by_scryfall.get(scryfall_id)
        if id_product is None:
            continue
        entry = json.loads(row["raw_json"])
        dated_prices = _retail_prices(entry, "normal")
        if not dated_prices:
            dated_prices = _retail_prices(entry, "foil")
        if not dated_prices:
            continue
        for snapshot_date, price in dated_prices.items():
            pending.append(
                {
                    "id_product": id_product,
                    "snapshot_date": snapshot_date,
                    "trend": price,
                    "low_price": None,
                    "avg": None,
                    "avg1": None,
                    "avg7": None,
                    "avg30": None,
                    "trend_foil": None,
                    "low_foil": None,
                    "avg_foil": None,
                    "avg1_foil": None,
                    "avg7_foil": None,
                    "avg30_foil": None,
                    "guide_version": None,
                    "guide_created_at": None,
                    "collected_at": collected_at,
                }
            )
            if len(pending) >= WRITE_BATCH_SIZE:
                flush()
        cards_processed += 1
        if cards_processed % 500 == 0:
            log(f"Backfill MTGJSON cache: {cards_processed}/{len(rows)} cartes")

    flush()
    log(f"Backfill termine: {rows_written} lignes guide depuis {cards_processed} cartes cache.")
    return {"cards_processed": cards_processed, "rows_written": rows_written}
