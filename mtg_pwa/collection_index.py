from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from .database import catalog_table, connect, decimal_to_json, get_app_metadata, init_db, set_app_metadata, utc_now
from .sets_catalog import (
    RARITY_ORDER,
    _build_owned_cards_for_scryfall_ids,
    _build_owned_collection_cards_merged,
    card_sort_value,
    enrich_owned_cards_live_prices,
    parse_sort_spec,
)

DISPLAY_LANGS = ("fr", "en", "merge")
INCREMENTAL_REBUILD_THRESHOLD = 120
INDEX_ORPHAN_SYNC_KEY = "collection_index_orphan_sync"
INDEX_FULL_REBUILD_KEY = "collection_index_full_rebuild"

ProgressCallback = Callable[[dict[str, Any]], None] | None

_INDEX_LOCK = threading.Lock()
_INDEX_REBUILD_STATE: dict[str, Any] = {
    "running": False,
    "display_lang": None,
    "built": 0,
    "total": 0,
    "started_at": None,
}


def index_rebuild_status() -> dict[str, Any]:
    with _INDEX_LOCK:
        return dict(_INDEX_REBUILD_STATE)


def ensure_collection_app_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collection_owned_index (
            scryfall_id TEXT NOT NULL,
            display_lang TEXT NOT NULL,
            display_scryfall_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            sort_name TEXT,
            sort_price REAL,
            sort_number TEXT,
            sort_rarity INTEGER,
            sort_cmc REAL,
            sort_set TEXT,
            sort_type TEXT,
            sort_subtype TEXT,
            sort_color TEXT,
            sort_finish TEXT,
            sort_quantity INTEGER,
            set_code TEXT,
            rarity TEXT,
            colors TEXT,
            has_foil INTEGER NOT NULL DEFAULT 0,
            no_price INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (scryfall_id, display_lang)
        );

        CREATE INDEX IF NOT EXISTS idx_owned_index_lang_name
            ON collection_owned_index(display_lang, sort_name);
        CREATE INDEX IF NOT EXISTS idx_owned_index_lang_set
            ON collection_owned_index(display_lang, set_code);
        CREATE INDEX IF NOT EXISTS idx_owned_index_lang_price
            ON collection_owned_index(display_lang, sort_price);

        CREATE TABLE IF NOT EXISTS collection_summary_cache (
            display_lang TEXT PRIMARY KEY,
            unique_lines INTEGER NOT NULL,
            total_cards INTEGER NOT NULL,
            total_value_eur REAL NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wishlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL DEFAULT 'nonfoil',
            quantity INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 0,
            max_price_eur REAL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (scryfall_id, finish)
        );

        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL DEFAULT 'nonfoil',
            direction TEXT NOT NULL DEFAULT 'below',
            threshold_eur REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'cardmarket',
            created_at TEXT NOT NULL,
            triggered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS binder_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            binder_name TEXT NOT NULL DEFAULT 'Principal',
            page_number INTEGER NOT NULL DEFAULT 1,
            slot_number INTEGER NOT NULL DEFAULT 1,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL DEFAULT 'nonfoil',
            condition TEXT NOT NULL DEFAULT 'near_mint',
            quantity INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collection_index_dirty (
            scryfall_id TEXT NOT NULL,
            display_lang TEXT NOT NULL,
            PRIMARY KEY (scryfall_id, display_lang)
        );

        CREATE TABLE IF NOT EXISTS price_alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL,
            direction TEXT NOT NULL,
            threshold_eur REAL NOT NULL,
            triggered_eur REAL NOT NULL,
            triggered_at TEXT NOT NULL,
            name TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_price_alert_events_at
            ON price_alert_events(triggered_at DESC);

        CREATE TABLE IF NOT EXISTS phantom_foil_ignored (
            id_product INTEGER PRIMARY KEY,
            ignored_at TEXT NOT NULL
        );
        """
    )


def mark_collection_index_dirty(
    conn,
    scryfall_ids: set[str] | None = None,
    *,
    full_rebuild: bool = False,
    orphan_sync: bool = False,
) -> None:
    ensure_collection_app_tables(conn)
    if full_rebuild:
        set_app_metadata(conn, INDEX_FULL_REBUILD_KEY, "1")
        conn.execute("DELETE FROM collection_index_dirty")
        return
    if orphan_sync:
        set_app_metadata(conn, INDEX_ORPHAN_SYNC_KEY, "1")
    if scryfall_ids:
        for scryfall_id in scryfall_ids:
            if not scryfall_id:
                continue
            for lang in DISPLAY_LANGS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO collection_index_dirty (scryfall_id, display_lang)
                    VALUES (?, ?)
                    """,
                    (scryfall_id, lang),
                )


def invalidate_collection_owned_index(
    conn,
    *,
    display_lang: str | None = None,
    scryfall_ids: set[str] | None = None,
    full_rebuild: bool = False,
) -> None:
    ensure_collection_app_tables(conn)
    if full_rebuild or display_lang is None and scryfall_ids is None:
        mark_collection_index_dirty(conn, full_rebuild=True)
        if display_lang:
            conn.execute("DELETE FROM collection_owned_index WHERE display_lang = ?", (display_lang.lower(),))
            conn.execute("DELETE FROM collection_summary_cache WHERE display_lang = ?", (display_lang.lower(),))
        else:
            conn.execute("DELETE FROM collection_owned_index")
            conn.execute("DELETE FROM collection_summary_cache")
        return
    mark_collection_index_dirty(conn, scryfall_ids, orphan_sync=scryfall_ids is None)
    if display_lang:
        conn.execute("DELETE FROM collection_summary_cache WHERE display_lang = ?", (display_lang.lower(),))
    else:
        conn.execute("DELETE FROM collection_summary_cache")


def collection_index_is_ready(conn, display_lang: str) -> bool:
    ensure_collection_app_tables(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM collection_owned_index WHERE display_lang = ?",
        (display_lang.lower(),),
    ).fetchone()
    return int(row["c"] or 0) > 0


def _index_sort_columns(card: dict[str, Any]) -> dict[str, Any]:
    colors = card.get("colors") or []
    return {
        "sort_name": (card.get("name") or "").lower(),
        "sort_price": float(card_sort_value(card, "price") or 0),
        "sort_number": str(card.get("number") or ""),
        "sort_rarity": RARITY_ORDER.get((card.get("rarity") or "").lower(), -1),
        "sort_cmc": float(card.get("cmc") or 0),
        "sort_set": (card.get("set_name") or card.get("set_code") or "").lower(),
        "sort_type": card.get("card_type") or "",
        "sort_subtype": card.get("subtype") or "",
        "sort_color": "".join(sorted(colors)),
        "sort_finish": (card.get("finish") or "").lower(),
        "sort_quantity": int(card.get("quantity") or 0),
    }


def _upsert_index_card(conn, lang: str, card: dict[str, Any]) -> None:
    breakdown = card.get("finish_breakdown") or {}
    has_foil = 1 if breakdown.get("foil") or card.get("finish") == "foil" else 0
    no_price = 1 if card.get("unit_price_eur") in (None, 0) else 0
    sort_cols = _index_sort_columns(card)
    payload = {key: value for key, value in card.items() if key != "display_scryfall_id"}
    conn.execute(
        """
        INSERT INTO collection_owned_index (
            scryfall_id, display_lang, display_scryfall_id, payload,
            sort_name, sort_price, sort_number, sort_rarity, sort_cmc,
            sort_set, sort_type, sort_subtype, sort_color, sort_finish, sort_quantity,
            set_code, rarity, colors, has_foil, no_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id, display_lang) DO UPDATE SET
            display_scryfall_id = excluded.display_scryfall_id,
            payload = excluded.payload,
            sort_name = excluded.sort_name,
            sort_price = excluded.sort_price,
            sort_number = excluded.sort_number,
            sort_rarity = excluded.sort_rarity,
            sort_cmc = excluded.sort_cmc,
            sort_set = excluded.sort_set,
            sort_type = excluded.sort_type,
            sort_subtype = excluded.sort_subtype,
            sort_color = excluded.sort_color,
            sort_finish = excluded.sort_finish,
            sort_quantity = excluded.sort_quantity,
            set_code = excluded.set_code,
            rarity = excluded.rarity,
            colors = excluded.colors,
            has_foil = excluded.has_foil,
            no_price = excluded.no_price
        """,
        (
            card["scryfall_id"],
            lang,
            card.get("display_scryfall_id") or card["scryfall_id"],
            json.dumps(payload, ensure_ascii=False),
            sort_cols["sort_name"],
            sort_cols["sort_price"],
            sort_cols["sort_number"],
            sort_cols["sort_rarity"],
            sort_cols["sort_cmc"],
            sort_cols["sort_set"],
            sort_cols["sort_type"],
            sort_cols["sort_subtype"],
            sort_cols["sort_color"],
            sort_cols["sort_finish"],
            sort_cols["sort_quantity"],
            (card.get("set_code") or "").lower(),
            (card.get("rarity") or "").lower(),
            json.dumps(card.get("colors") or []),
            has_foil,
            no_price,
        ),
    )


def _refresh_collection_summary_cache(conn, display_lang: str) -> None:
    lang = display_lang.lower()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS unique_lines,
            COALESCE(SUM(sort_quantity), 0) AS total_cards,
            COALESCE(SUM(CAST(json_extract(payload, '$.line_value_eur') AS REAL)), 0) AS total_value
        FROM collection_owned_index
        WHERE display_lang = ?
        """,
        (lang,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO collection_summary_cache (
            display_lang, unique_lines, total_cards, total_value_eur, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(display_lang) DO UPDATE SET
            unique_lines = excluded.unique_lines,
            total_cards = excluded.total_cards,
            total_value_eur = excluded.total_value_eur,
            updated_at = excluded.updated_at
        """,
        (
            lang,
            int(row["unique_lines"] or 0),
            int(row["total_cards"] or 0),
            float(row["total_value"] or 0),
            utc_now(),
        ),
    )


def _remove_orphan_index_rows(conn) -> None:
    conn.execute(
        """
        DELETE FROM collection_owned_index
        WHERE scryfall_id NOT IN (
            SELECT DISTINCT scryfall_id FROM collection_items WHERE quantity > 0
        )
        """
    )


def _incremental_sync_lang(
    conn,
    lang: str,
    scryfall_ids: set[str],
    *,
    on_progress: ProgressCallback = None,
) -> None:
    owned_ids = {
        row["scryfall_id"]
        for row in conn.execute(
            "SELECT DISTINCT scryfall_id FROM collection_items WHERE quantity > 0"
        ).fetchall()
    }
    total = len(scryfall_ids)
    for index, scryfall_id in enumerate(sorted(scryfall_ids), start=1):
        if scryfall_id not in owned_ids:
            conn.execute(
                "DELETE FROM collection_owned_index WHERE scryfall_id = ? AND display_lang = ?",
                (scryfall_id, lang),
            )
        else:
            cards = _build_owned_cards_for_scryfall_ids(
                conn,
                {scryfall_id},
                display_lang=lang,
                include_live_prices=False,
            )
            if cards:
                _upsert_index_card(conn, lang, cards[0])
            else:
                conn.execute(
                    "DELETE FROM collection_owned_index WHERE scryfall_id = ? AND display_lang = ?",
                    (scryfall_id, lang),
                )
        if on_progress and (index == 1 or index % 25 == 0 or index == total):
            on_progress({"built": index, "total": total, "incremental": True})
    _refresh_collection_summary_cache(conn, lang)


def sync_collection_owned_index(
    conn,
    display_lang: str,
    *,
    on_progress: ProgressCallback = None,
) -> None:
    ensure_collection_app_tables(conn)
    lang = display_lang.lower()
    full_flag = get_app_metadata(conn, INDEX_FULL_REBUILD_KEY)
    dirty_count = int(
        conn.execute("SELECT COUNT(*) AS c FROM collection_index_dirty").fetchone()["c"] or 0
    )
    orphan_sync = get_app_metadata(conn, INDEX_ORPHAN_SYNC_KEY) == "1"

    if full_flag == "1" or not collection_index_is_ready(conn, lang):
        set_app_metadata(conn, INDEX_FULL_REBUILD_KEY, "")
        conn.execute("DELETE FROM collection_index_dirty")
        for sync_lang in DISPLAY_LANGS:
            rebuild_collection_owned_index(conn, display_lang=sync_lang, on_progress=on_progress if sync_lang == lang else None)
        return

    if dirty_count == 0 and not orphan_sync:
        return

    if dirty_count > INCREMENTAL_REBUILD_THRESHOLD:
        conn.execute("DELETE FROM collection_index_dirty")
        for sync_lang in DISPLAY_LANGS:
            rebuild_collection_owned_index(conn, display_lang=sync_lang, on_progress=on_progress if sync_lang == lang else None)
        return

    if orphan_sync:
        _remove_orphan_index_rows(conn)
        set_app_metadata(conn, INDEX_ORPHAN_SYNC_KEY, "")

    dirty_rows = conn.execute(
        "SELECT scryfall_id, display_lang FROM collection_index_dirty"
    ).fetchall()
    dirty_by_lang: dict[str, set[str]] = {}
    for row in dirty_rows:
        dirty_by_lang.setdefault(row["display_lang"], set()).add(row["scryfall_id"])

    with _INDEX_LOCK:
        _INDEX_REBUILD_STATE.update(
            {
                "running": True,
                "display_lang": lang,
                "built": 0,
                "total": sum(len(ids) for ids in dirty_by_lang.values()),
                "started_at": time.time(),
            }
        )

    try:
        for sync_lang, ids in dirty_by_lang.items():
            _incremental_sync_lang(conn, sync_lang, ids, on_progress=on_progress)
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                DELETE FROM collection_index_dirty
                WHERE display_lang = ? AND scryfall_id IN ({placeholders})
                """,
                (sync_lang, *sorted(ids)),
            )
        conn.commit()
    finally:
        with _INDEX_LOCK:
            _INDEX_REBUILD_STATE["running"] = False


_INDEX_BG_LOCK = threading.Lock()
_INDEX_BG_SCHEDULED = False


def schedule_collection_index_sync(display_langs: tuple[str, ...] | None = None) -> None:
    """Sync dirty index rows in a background thread (non-blocking)."""
    global _INDEX_BG_SCHEDULED
    langs = display_langs or DISPLAY_LANGS

    def worker() -> None:
        global _INDEX_BG_SCHEDULED
        try:
            conn = connect()
            init_db(conn)
            for lang in langs:
                sync_collection_owned_index(conn, lang)
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001 - background sync must not crash the app.
            pass
        finally:
            with _INDEX_BG_LOCK:
                _INDEX_BG_SCHEDULED = False

    with _INDEX_BG_LOCK:
        if _INDEX_BG_SCHEDULED or _INDEX_REBUILD_STATE.get("running"):
            return
        _INDEX_BG_SCHEDULED = True
    threading.Thread(target=worker, daemon=True, name="collection-index-sync").start()


def rebuild_collection_owned_index(
    conn,
    *,
    display_lang: str,
    on_progress: ProgressCallback = None,
) -> dict[str, int]:
    ensure_collection_app_tables(conn)
    lang = display_lang.lower()
    with _INDEX_LOCK:
        _INDEX_REBUILD_STATE.update(
            {
                "running": True,
                "display_lang": lang,
                "built": 0,
                "total": 0,
                "started_at": time.time(),
            }
        )

    try:
        cards = _build_owned_collection_cards_merged(
            conn,
            sort="name_asc",
            display_lang=lang,
            include_live_prices=False,
        )
        total = len(cards)
        with _INDEX_LOCK:
            _INDEX_REBUILD_STATE["total"] = total

        conn.execute("DELETE FROM collection_owned_index WHERE display_lang = ?", (lang,))
        now = utc_now()
        total_cards = 0
        total_value = Decimal("0")
        for index, card in enumerate(cards, start=1):
            _upsert_index_card(conn, lang, card)
            qty = int(card.get("quantity") or 0)
            total_cards += qty
            total_value += Decimal(str(card.get("line_value_eur") or 0))
            if on_progress and (index == 1 or index % 50 == 0 or index == total):
                on_progress({"built": index, "total": total})
            with _INDEX_LOCK:
                _INDEX_REBUILD_STATE["built"] = index

        conn.execute(
            """
            INSERT INTO collection_summary_cache (
                display_lang, unique_lines, total_cards, total_value_eur, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(display_lang) DO UPDATE SET
                unique_lines = excluded.unique_lines,
                total_cards = excluded.total_cards,
                total_value_eur = excluded.total_value_eur,
                updated_at = excluded.updated_at
            """,
            (lang, total, total_cards, float(total_value), now),
        )
        conn.commit()
        return {"indexed": total, "total_cards": total_cards}
    finally:
        with _INDEX_LOCK:
            _INDEX_REBUILD_STATE["running"] = False


def ensure_collection_owned_index(
    conn,
    display_lang: str,
    *,
    on_progress: ProgressCallback = None,
    background_ok: bool = False,
) -> None:
    lang = display_lang.lower()
    dirty_for_lang = int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM collection_index_dirty WHERE display_lang = ?",
            (lang,),
        ).fetchone()["c"]
        or 0
    )
    if background_ok and dirty_for_lang > 0 and collection_index_is_ready(conn, lang):
        schedule_collection_index_sync((lang,))
        return
    sync_collection_owned_index(conn, display_lang, on_progress=on_progress)


@dataclass
class MyCollectionFilters:
    q: str = ""
    set_code: str = ""
    rarity: str = ""
    color: str = ""
    foil_only: bool = False
    no_price: bool = False


def _query_one(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key) or []
    return values[0] if values else default


def parse_my_collection_filters(query: dict[str, list[str]]) -> MyCollectionFilters:
    return MyCollectionFilters(
        q=_query_one(query, "q", "").strip().lower(),
        set_code=_query_one(query, "set", "").strip().lower(),
        rarity=_query_one(query, "rarity", "").strip().lower(),
        color=_query_one(query, "color", "").strip().upper(),
        foil_only=_query_one(query, "foil_only", "0").lower() in {"1", "true", "yes", "on"},
        no_price=_query_one(query, "no_price", "0").lower() in {"1", "true", "yes", "on"},
    )


def _sql_order_clause(sort: str) -> str:
    mapping = {
        "name": "sort_name",
        "price": "sort_price",
        "number": "sort_number",
        "rarity": "sort_rarity",
        "cmc": "sort_cmc",
        "set": "sort_set",
        "type": "sort_type",
        "subtype": "sort_subtype",
        "color": "sort_color",
        "finish": "sort_finish",
        "quantity": "sort_quantity",
    }
    parts: list[str] = []
    for field, reverse in parse_sort_spec(sort):
        column = mapping.get(field)
        if not column:
            continue
        direction = "DESC" if reverse else "ASC"
        parts.append(f"{column} {direction}")
    if not parts:
        parts.append("sort_name ASC")
    return ", ".join(parts)


def _filter_where(display_lang: str, filters: MyCollectionFilters) -> tuple[str, list[Any]]:
    clauses = ["display_lang = ?"]
    params: list[Any] = [display_lang.lower()]
    if filters.q:
        clauses.append("(LOWER(sort_name) LIKE ? OR LOWER(payload) LIKE ?)")
        params.extend([f"%{filters.q}%", f"%{filters.q}%"])
    if filters.set_code:
        clauses.append("set_code = ?")
        params.append(filters.set_code)
    if filters.rarity:
        clauses.append("rarity = ?")
        params.append(filters.rarity)
    if filters.color:
        clauses.append("colors LIKE ?")
        params.append(f'%"{filters.color}"%')
    if filters.foil_only:
        clauses.append("has_foil = 1")
    if filters.no_price:
        clauses.append("no_price = 1")
    return " AND ".join(clauses), params


def get_cached_collection_summary(conn, display_lang: str) -> dict[str, Any] | None:
    ensure_collection_app_tables(conn)
    row = conn.execute(
        "SELECT unique_lines, total_cards, total_value_eur FROM collection_summary_cache WHERE display_lang = ?",
        (display_lang.lower(),),
    ).fetchone()
    if row is None:
        return None
    return {
        "unique_lines": int(row["unique_lines"]),
        "total_cards": int(row["total_cards"]),
        "total_value_eur": decimal_to_json(Decimal(str(row["total_value_eur"]))),
    }


def list_owned_from_index(
    conn,
    *,
    sort: str,
    display_lang: str,
    limit: int,
    offset: int,
    filters: MyCollectionFilters | None = None,
    on_progress: ProgressCallback = None,
) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    lang = display_lang.lower()
    ensure_collection_owned_index(conn, lang, on_progress=on_progress, background_ok=True)

    filters = filters or MyCollectionFilters()
    where_sql, where_params = _filter_where(lang, filters)
    count_row = conn.execute(
        f"SELECT COUNT(*) AS c FROM collection_owned_index WHERE {where_sql}",
        where_params,
    ).fetchone()
    total = int(count_row["c"] or 0)

    order_sql = _sql_order_clause(sort)
    rows = conn.execute(
        f"""
        SELECT payload
        FROM collection_owned_index
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
        """,
        where_params + [limit, offset],
    ).fetchall()

    page_cards = [json.loads(row["payload"]) for row in rows]
    enrich_owned_cards_live_prices(conn, page_cards)

    summary = get_cached_collection_summary(conn, lang)
    if summary is None:
        summary = {"unique_lines": total, "total_cards": 0, "total_value_eur": decimal_to_json(Decimal("0"))}

    page = (offset // limit) + 1 if limit else 1
    total_pages = max(1, (total + limit - 1) // limit) if limit else 1
    return {
        "summary": summary,
        "cards": page_cards,
        "pagination": {
            "total": total,
            "offset": offset,
            "page_size": limit,
            "page": page,
            "total_pages": total_pages,
            "filtered_total": total,
        },
        "meta": {
            "index": True,
            "filters": {
                "q": filters.q,
                "set": filters.set_code,
                "rarity": filters.rarity,
                "color": filters.color,
                "foil_only": filters.foil_only,
                "no_price": filters.no_price,
            },
        },
    }
