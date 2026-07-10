from __future__ import annotations

from typing import Any

from .database import (
    cached_mtgjson_price_entry,
    cached_mtgjson_uuid,
    catalog_table,
    display_price_for,
    get_cached_card,
)
from .mtgjson import normalize_price_points
from .prices import available_finishes_for_card, current_eur_price


def scryfall_prices_fresh(conn, card: dict[str, Any]) -> bool:
    """True when local Scryfall snapshots match the card's updated_at."""
    updated_at = card.get("updated_at")
    if not updated_at:
        return False
    from .price_daily import reads_price_daily

    if reads_price_daily(conn):
        row = conn.execute(
            """
            SELECT source_updated_at
            FROM price_daily
            WHERE scryfall_id = ?
              AND sf_cm_nonfoil IS NOT NULL
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (card["id"],),
        ).fetchone()
        if row is not None and row[0]:
            return row[0] == updated_at

    snapshots_table = catalog_table("price_snapshots")
    row = conn.execute(
        f"""
        SELECT source_updated_at
        FROM {snapshots_table}
        WHERE scryfall_id = ? AND source = 'scryfall-cardmarket'
        ORDER BY collected_at DESC
        LIMIT 1
        """,
        (card["id"],),
    ).fetchone()
    if row is None:
        return False
    return row["source_updated_at"] == updated_at


def needs_price_fallback(conn, card: dict[str, Any]) -> bool:
    """True when a non-English print still lacks a display price for a finish."""
    if card.get("lang") == "en":
        return False
    for finish in available_finishes_for_card(card):
        if current_eur_price(card, finish) is not None:
            continue
        if display_price_for(conn, card, finish) is None:
            return True
    return False


def mtgjson_snapshots_need_sync(
    conn,
    scryfall_id: str,
    points: list[dict[str, Any]],
) -> bool:
    mtgjson_points = [point for point in points if str(point.get("source", "")).startswith("mtgjson-")]
    if not mtgjson_points:
        return False

    from .price_daily import column_for_point, reads_price_daily

    trackable_points = [
        point
        for point in mtgjson_points
        if column_for_point(str(point.get("source") or ""), str(point.get("finish") or "nonfoil"))
    ]
    if not trackable_points:
        return False

    if reads_price_daily(conn):
        latest_by_source: dict[str, str] = {}
        for point in trackable_points:
            source = point["source"]
            snapshot_date = point["snapshot_date"]
            if source not in latest_by_source or snapshot_date > latest_by_source[source]:
                latest_by_source[source] = snapshot_date
        stored_count = 0
        for source, file_latest in latest_by_source.items():
            finish = next(
                (str(point.get("finish") or "nonfoil") for point in trackable_points if point["source"] == source),
                "nonfoil",
            )
            column = column_for_point(source, finish)
            if column is None:
                continue
            row = conn.execute(
                f"""
                SELECT MAX(snapshot_date) AS latest, COUNT({column}) AS quantity
                FROM price_daily
                WHERE scryfall_id = ? AND {column} IS NOT NULL
                """,
                (scryfall_id,),
            ).fetchone()
            stored_count += int(row[1] or 0)
            db_latest = row[0]
            if db_latest is None or db_latest < file_latest:
                return True
        return stored_count < int(len(trackable_points) * 0.75)

    snapshots_table = catalog_table("price_snapshots")
    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS quantity
        FROM {snapshots_table}
        WHERE scryfall_id = ? AND source LIKE 'mtgjson-%'
        """,
        (scryfall_id,),
    ).fetchone()
    stored_count = int(count_row["quantity"] or 0)
    if stored_count == 0:
        return True

    latest_by_source: dict[str, str] = {}
    for point in mtgjson_points:
        source = point["source"]
        snapshot_date = point["snapshot_date"]
        if source not in latest_by_source or snapshot_date > latest_by_source[source]:
            latest_by_source[source] = snapshot_date

    for source, file_latest in latest_by_source.items():
        row = conn.execute(
            f"""
            SELECT MAX(snapshot_date) AS latest
            FROM {snapshots_table}
            WHERE scryfall_id = ? AND source = ?
            """,
            (scryfall_id, source),
        ).fetchone()
        db_latest = row["latest"]
        if db_latest is None or db_latest < file_latest:
            return True

    return stored_count < int(len(mtgjson_points) * 0.75)


def mtgjson_prices_fresh(conn, card: dict[str, Any]) -> bool:
    """True when cached MTGJSON data is present and snapshots are in sync."""
    mtgjson_uuid = cached_mtgjson_uuid(conn, card["id"])
    if mtgjson_uuid is None:
        return False
    price_entry = cached_mtgjson_price_entry(conn, mtgjson_uuid)
    if price_entry is None:
        return False
    points = normalize_price_points(card["id"], price_entry)
    return not mtgjson_snapshots_need_sync(conn, card["id"], points)


def card_price_sync_plan(conn, scryfall_id: str) -> dict[str, bool]:
    """Decide which network/local steps a card needs."""
    card = get_cached_card(conn, scryfall_id)
    if card is None:
        return {
            "needs_scryfall": True,
            "needs_fallback": False,
            "needs_mtgjson": True,
            "skip": False,
        }

    needs_scryfall = not scryfall_prices_fresh(conn, card)
    needs_fallback = needs_price_fallback(conn, card)
    needs_mtgjson = not mtgjson_prices_fresh(conn, card)
    skip = not needs_scryfall and not needs_fallback and not needs_mtgjson
    return {
        "needs_scryfall": needs_scryfall,
        "needs_fallback": needs_fallback,
        "needs_mtgjson": needs_mtgjson,
        "skip": skip,
    }
