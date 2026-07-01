from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .local_cache import local_image_url
from .prices import (
    CHART_PRICE_SOURCES,
    PricePoint,
    available_finishes_for_card,
    chart_price_source,
    chart_price_source_keys,
    current_eur_price,
    decimal_to_json,
    extract_eur_prices,
)


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mtg_pwa.sqlite3"
SHARED_PRICES_DB_ENV = "MTG_PWA_PRICES_DB"
SHARED_CATALOG_SCHEMA = "shared"
SHARED_CATALOG_TABLES = (
    "cards",
    "price_snapshots",
    "mtgjson_card_map",
    "mtgjson_price_cache",
    "cardmarket_product_map",
    "cardmarket_price_guide_daily",
)
PRICE_PERIODS = {
    "1d": 1,
    "1m": 30,
    "6m": 183,
    "1y": 365,
    "5y": 1825,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def shared_prices_db_path() -> Path | None:
    raw = os.environ.get(SHARED_PRICES_DB_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def uses_shared_catalog() -> bool:
    return shared_prices_db_path() is not None


def catalog_table(table_name: str) -> str:
    if uses_shared_catalog():
        return f"{SHARED_CATALOG_SCHEMA}.{table_name}"
    return table_name


def attach_shared_catalog(conn: sqlite3.Connection) -> None:
    shared_path = shared_prices_db_path()
    if shared_path is None:
        return
    if not shared_path.exists():
        raise FileNotFoundError(f"Base prix partagee introuvable: {shared_path}")
    conn.execute(f"ATTACH DATABASE ? AS {SHARED_CATALOG_SCHEMA}", (str(shared_path),))


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    attach_shared_catalog(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    shared_catalog = uses_shared_catalog()
    collection_fk = "" if shared_catalog else ",\n            FOREIGN KEY (scryfall_id) REFERENCES cards(scryfall_id)"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS collection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scryfall_id TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            finish TEXT NOT NULL DEFAULT 'nonfoil',
            condition TEXT NOT NULL DEFAULT 'near_mint',
            language TEXT,
            purchase_price REAL,
            purchase_currency TEXT NOT NULL DEFAULT 'EUR',
            purchase_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL{collection_fk}
        );

        CREATE TABLE IF NOT EXISTS owned_decks (
            file_name TEXT PRIMARY KEY,
            owned_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS owned_deck_dismissals (
            file_name TEXT PRIMARY KEY,
            dismissed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    if not shared_catalog:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                scryfall_id TEXT PRIMARY KEY,
                oracle_id TEXT,
                name TEXT NOT NULL,
                printed_name TEXT,
                lang TEXT,
                set_code TEXT,
                set_name TEXT,
                collector_number TEXT,
                rarity TEXT,
                image_url TEXT,
                scryfall_uri TEXT,
                raw_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scryfall_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                finish TEXT NOT NULL,
                price REAL NOT NULL,
                source TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                source_updated_at TEXT,
                UNIQUE (scryfall_id, currency, finish, source, snapshot_date),
                FOREIGN KEY (scryfall_id) REFERENCES cards(scryfall_id)
            );

            CREATE TABLE IF NOT EXISTS mtgjson_card_map (
                scryfall_id TEXT PRIMARY KEY,
                mtgjson_uuid TEXT NOT NULL,
                set_code TEXT,
                collector_number TEXT,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mtgjson_price_cache (
                mtgjson_uuid TEXT PRIMARY KEY,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cardmarket_product_map (
                id_product INTEGER PRIMARY KEY,
                scryfall_id TEXT NOT NULL UNIQUE,
                set_code TEXT,
                collector_number TEXT,
                mapped_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cardmarket_price_guide_daily (
                id_product INTEGER NOT NULL,
                snapshot_date TEXT NOT NULL,
                trend REAL,
                low_price REAL,
                avg REAL,
                avg1 REAL,
                avg7 REAL,
                avg30 REAL,
                trend_foil REAL,
                low_foil REAL,
                avg_foil REAL,
                avg1_foil REAL,
                avg7_foil REAL,
                avg30_foil REAL,
                guide_version INTEGER,
                guide_created_at TEXT,
                collected_at TEXT NOT NULL,
                PRIMARY KEY (id_product, snapshot_date)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
            CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON cards(oracle_id);
            CREATE INDEX IF NOT EXISTS idx_collection_card ON collection_items(scryfall_id);
            CREATE INDEX IF NOT EXISTS idx_price_card_finish ON price_snapshots(scryfall_id, finish, currency, snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_cards_set_code ON cards(set_code);
            CREATE INDEX IF NOT EXISTS idx_cards_set_collector ON cards(set_code, collector_number);
            CREATE INDEX IF NOT EXISTS idx_price_market_lookup
                ON price_snapshots(finish, currency, source, snapshot_date, scryfall_id);
            CREATE INDEX IF NOT EXISTS idx_price_card_source_date
                ON price_snapshots(scryfall_id, finish, currency, source, snapshot_date);
            """
        )
    else:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_collection_card ON collection_items(scryfall_id);
            """
        )
    ensure_catalog_indexes(conn)
    ensure_cardmarket_schema(conn)
    conn.commit()
    backfill_owned_decks_from_imports(conn)


def ensure_cardmarket_schema(conn: sqlite3.Connection) -> None:
    shared_catalog = uses_shared_catalog()
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    index_sql = (
        ""
        if shared_catalog
        else f"""
        CREATE INDEX IF NOT EXISTS idx_cm_guide_product_date
            ON {guide_table}(id_product, snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_cm_guide_snapshot_date
            ON {guide_table}(snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_cm_map_scryfall
            ON {map_table}(scryfall_id);
        CREATE INDEX IF NOT EXISTS idx_cm_map_set_code
            ON {map_table}(set_code);
        """
    )
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {map_table} (
            id_product INTEGER PRIMARY KEY,
            scryfall_id TEXT NOT NULL UNIQUE,
            set_code TEXT,
            collector_number TEXT,
            mapped_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS {guide_table} (
            id_product INTEGER NOT NULL,
            snapshot_date TEXT NOT NULL,
            trend REAL,
            low_price REAL,
            avg REAL,
            avg1 REAL,
            avg7 REAL,
            avg30 REAL,
            trend_foil REAL,
            low_foil REAL,
            avg_foil REAL,
            avg1_foil REAL,
            avg7_foil REAL,
            avg30_foil REAL,
            guide_version INTEGER,
            guide_created_at TEXT,
            collected_at TEXT NOT NULL,
            PRIMARY KEY (id_product, snapshot_date)
        );
        {index_sql}
        """
    )


def ensure_catalog_indexes(conn: sqlite3.Connection) -> None:
    if uses_shared_catalog():
        # Index created when the shared prices DB is initialized standalone.
        return
    cards_table = catalog_table("cards")
    snapshots_table = catalog_table("price_snapshots")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_cards_set_code ON {cards_table}(set_code)")
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_cards_set_collector ON {cards_table}(set_code, collector_number)"
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_price_market_lookup
        ON {snapshots_table}(finish, currency, source, snapshot_date, scryfall_id)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_price_card_source_date
        ON {snapshots_table}(scryfall_id, finish, currency, source, snapshot_date)
        """
    )


def image_url_for(card: dict[str, Any]) -> str | None:
    image_uris = card.get("image_uris") or {}
    if image_uris.get("normal"):
        return image_uris["normal"]
    if image_uris.get("large"):
        return image_uris["large"]

    faces = card.get("card_faces") or []
    for face in faces:
        face_images = face.get("image_uris") or {}
        if face_images.get("normal"):
            return face_images["normal"]
        if face_images.get("large"):
            return face_images["large"]
    return None


def large_image_url_for(card: dict[str, Any]) -> str | None:
    image_uris = card.get("image_uris") or {}
    if image_uris.get("large"):
        return image_uris["large"]
    if image_uris.get("normal"):
        return image_uris["normal"]

    faces = card.get("card_faces") or []
    for face in faces:
        face_images = face.get("image_uris") or {}
        if face_images.get("large"):
            return face_images["large"]
        if face_images.get("normal"):
            return face_images["normal"]
    return None


def save_card(conn: sqlite3.Connection, card: dict[str, Any]) -> None:
    now = utc_now()
    cards_table = catalog_table("cards")
    conn.execute(
        f"""
        INSERT INTO {cards_table} (
            scryfall_id, oracle_id, name, printed_name, lang, set_code, set_name,
            collector_number, rarity, image_url, scryfall_uri, raw_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id) DO UPDATE SET
            oracle_id = excluded.oracle_id,
            name = excluded.name,
            printed_name = excluded.printed_name,
            lang = excluded.lang,
            set_code = excluded.set_code,
            set_name = excluded.set_name,
            collector_number = excluded.collector_number,
            rarity = excluded.rarity,
            image_url = excluded.image_url,
            scryfall_uri = excluded.scryfall_uri,
            raw_json = excluded.raw_json,
            updated_at = excluded.updated_at
        """,
        (
            card["id"],
            card.get("oracle_id"),
            card.get("name") or card.get("printed_name") or "Unknown card",
            card.get("printed_name"),
            card.get("lang"),
            card.get("set"),
            card.get("set_name"),
            card.get("collector_number"),
            card.get("rarity"),
            image_url_for(card),
            card.get("scryfall_uri"),
            json.dumps(card, ensure_ascii=False),
            now,
        ),
    )


def save_cards(conn: sqlite3.Connection, cards: Iterable[dict[str, Any]]) -> None:
    for card in cards:
        save_card(conn, card)
        save_price_snapshots(conn, card)
    conn.commit()


def save_price_snapshots(conn: sqlite3.Connection, card: dict[str, Any]) -> int:
    now = utc_now()
    snapshot_date = now[:10]
    prices = extract_eur_prices(card)
    saved = 0

    for finish, price in prices.items():
        snapshots_table = catalog_table("price_snapshots")
        conn.execute(
            f"""
            INSERT INTO {snapshots_table} (
                scryfall_id, currency, finish, price, source, snapshot_date,
                collected_at, source_updated_at
            )
            VALUES (?, 'EUR', ?, ?, 'scryfall-cardmarket', ?, ?, ?)
            ON CONFLICT(scryfall_id, currency, finish, source, snapshot_date)
            DO UPDATE SET
                price = excluded.price,
                collected_at = excluded.collected_at,
                source_updated_at = excluded.source_updated_at
            """,
            (
                card["id"],
                finish,
                float(price),
                snapshot_date,
                now,
                card.get("updated_at"),
            ),
        )
        saved += 1

    return saved


def save_fallback_price_snapshot(
    conn: sqlite3.Connection,
    *,
    scryfall_id: str,
    finish: str,
    price: Decimal,
    source: str,
    source_updated_at: str | None = None,
) -> None:
    now = utc_now()
    snapshot_date = now[:10]
    snapshots_table = catalog_table("price_snapshots")
    conn.execute(
        f"""
        INSERT INTO {snapshots_table} (
            scryfall_id, currency, finish, price, source, snapshot_date,
            collected_at, source_updated_at
        )
        VALUES (?, 'EUR', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id, currency, finish, source, snapshot_date)
        DO UPDATE SET
            price = excluded.price,
            collected_at = excluded.collected_at,
            source_updated_at = excluded.source_updated_at
        """,
        (
            scryfall_id,
            finish,
            float(price),
            source,
            snapshot_date,
            now,
            source_updated_at,
        ),
    )


def save_external_price_snapshots(conn: sqlite3.Connection, points: Iterable[dict[str, Any]]) -> int:
    snapshots_table = catalog_table("price_snapshots")
    sql = f"""
        INSERT INTO {snapshots_table} (
            scryfall_id, currency, finish, price, source, snapshot_date,
            collected_at, source_updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id, currency, finish, source, snapshot_date)
        DO UPDATE SET
            price = excluded.price,
            collected_at = excluded.collected_at
    """
    rows = [
        (
            point["scryfall_id"],
            point["currency"],
            point["finish"],
            point["price"],
            point["source"],
            point["snapshot_date"],
            point["collected_at"],
            point.get("source_updated_at"),
        )
        for point in points
    ]
    if not rows:
        return 0
    conn.executemany(sql, rows)
    return len(rows)


def cached_mtgjson_uuid(conn: sqlite3.Connection, scryfall_id: str) -> str | None:
    map_table = catalog_table("mtgjson_card_map")
    row = conn.execute(
        f"SELECT mtgjson_uuid FROM {map_table} WHERE scryfall_id = ?",
        (scryfall_id,),
    ).fetchone()
    if row is None:
        return None
    return row["mtgjson_uuid"]


def save_mtgjson_uuid(
    conn: sqlite3.Connection,
    *,
    scryfall_id: str,
    mtgjson_uuid: str,
    set_code: str | None,
    collector_number: str | None,
) -> None:
    map_table = catalog_table("mtgjson_card_map")
    conn.execute(
        f"""
        INSERT INTO {map_table} (
            scryfall_id, mtgjson_uuid, set_code, collector_number, fetched_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id) DO UPDATE SET
            mtgjson_uuid = excluded.mtgjson_uuid,
            set_code = excluded.set_code,
            collector_number = excluded.collector_number,
            fetched_at = excluded.fetched_at
        """,
        (scryfall_id, mtgjson_uuid, set_code, collector_number, utc_now()),
    )


def cached_mtgjson_price_entry(conn: sqlite3.Connection, mtgjson_uuid: str) -> dict[str, Any] | None:
    cache_table = catalog_table("mtgjson_price_cache")
    row = conn.execute(
        f"SELECT raw_json FROM {cache_table} WHERE mtgjson_uuid = ?",
        (mtgjson_uuid,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["raw_json"])


def save_mtgjson_price_entry(conn: sqlite3.Connection, mtgjson_uuid: str, price_entry: dict[str, Any]) -> None:
    cache_table = catalog_table("mtgjson_price_cache")
    conn.execute(
        f"""
        INSERT INTO {cache_table} (mtgjson_uuid, raw_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(mtgjson_uuid) DO UPDATE SET
            raw_json = excluded.raw_json,
            fetched_at = excluded.fetched_at
        """,
        (mtgjson_uuid, json.dumps(price_entry, ensure_ascii=False), utc_now()),
    )


def get_cached_card(conn: sqlite3.Connection, scryfall_id: str) -> dict[str, Any] | None:
    cards_table = catalog_table("cards")
    row = conn.execute(
        f"SELECT raw_json FROM {cards_table} WHERE scryfall_id = ?",
        (scryfall_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["raw_json"])


VALID_DISPLAY_LANG_MODES = frozenset({"fr", "en", "merge"})


def language_sibling_ids_db(conn: sqlite3.Connection, card: dict[str, Any]) -> dict[str, str]:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").strip()
    current_lang = str(card.get("lang") or "en").lower()
    if not set_code or not collector_number:
        return {current_lang: card["id"]}

    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT raw_json
        FROM {cards_table}
        WHERE lower(set_code) = ? AND collector_number = ?
        """,
        (set_code, collector_number),
    ).fetchall()
    ids: dict[str, str] = {}
    for row in rows:
        payload = json.loads(row["raw_json"])
        lang = str(payload.get("lang") or "en").lower()
        if lang in {"fr", "en"}:
            ids[lang] = payload["id"]
    ids.setdefault(current_lang, card["id"])
    return ids


def build_set_language_siblings(conn: sqlite3.Connection, set_code: str) -> dict[str, dict[str, str]]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT raw_json
        FROM {cards_table}
        WHERE lower(set_code) = ?
        """,
        (set_code.lower(),),
    ).fetchall()
    by_number: dict[str, dict[str, str]] = {}
    for row in rows:
        payload = json.loads(row["raw_json"])
        collector_number = str(payload.get("collector_number") or "").strip()
        lang = str(payload.get("lang") or "en").lower()
        if collector_number and lang in {"fr", "en"}:
            by_number.setdefault(collector_number, {})[lang] = payload["id"]
    return by_number


def resolve_display_card_id(
    card: dict[str, Any],
    siblings: dict[str, str],
    display_lang: str,
) -> str:
    if display_lang not in VALID_DISPLAY_LANG_MODES:
        display_lang = "merge"
    current_id = card["id"]
    fr_id = siblings.get("fr")
    en_id = siblings.get("en")
    if display_lang == "fr":
        return fr_id or current_id
    if display_lang == "en":
        return en_id or current_id
    return fr_id or en_id or current_id


def resolve_display_card_db(
    conn: sqlite3.Connection,
    card: dict[str, Any],
    display_lang: str,
    *,
    siblings: dict[str, str] | None = None,
    sibling_cache: dict[tuple[str, str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    if siblings is None:
        if sibling_cache is not None:
            set_code = str(card.get("set") or "").lower()
            collector_number = str(card.get("collector_number") or "").strip()
            cache_key = (set_code, collector_number)
            siblings = sibling_cache.get(cache_key)
            if siblings is None:
                siblings = language_sibling_ids_db(conn, card)
                sibling_cache[cache_key] = siblings
        else:
            siblings = language_sibling_ids_db(conn, card)
    target_id = resolve_display_card_id(card, siblings, display_lang)
    if target_id == card["id"]:
        return card
    cached = get_cached_card(conn, target_id)
    return cached if cached else card


def latest_snapshot(
    conn: sqlite3.Connection,
    scryfall_id: str,
    finish: str,
    currency: str = "EUR",
) -> PricePoint | None:
    snapshots_table = catalog_table("price_snapshots")
    row = conn.execute(
        f"""
        SELECT price, source
        FROM {snapshots_table}
        WHERE scryfall_id = ? AND finish = ? AND currency = ?
        ORDER BY snapshot_date DESC,
          CASE
            WHEN source = 'scryfall-cardmarket' THEN 0
            WHEN source LIKE 'scryfall-cardmarket-en-print:%' THEN 1
            ELSE 2
          END,
          collected_at DESC
        LIMIT 1
        """,
        (scryfall_id, finish, currency),
    ).fetchone()
    if row is None:
        return None
    source = str(row["source"] or "")
    is_fallback = not (
        source == "scryfall-cardmarket" or source.startswith("scryfall-cardmarket-en-print:")
    )
    return PricePoint(
        currency=currency,
        finish=finish,
        price=Decimal(str(row["price"])),
        source=source,
        is_fallback=is_fallback,
    )


def display_price_for(
    conn: sqlite3.Connection,
    card: dict[str, Any],
    finish: str,
) -> PricePoint | None:
    current = current_eur_price(card, finish)
    if current is not None:
        return current
    return latest_snapshot(conn, card["id"], finish)


def card_summary(conn: sqlite3.Connection, card: dict[str, Any], finish: str = "nonfoil") -> dict[str, Any]:
    owned_by_finish = collection_quantities_for_card(conn, card["id"])
    available_finishes = available_finishes_for_card(card, extra_finishes=owned_by_finish.keys())
    display_finish = finish
    if available_finishes and finish not in available_finishes:
        display_finish = available_finishes[0]
    price = display_price_for(conn, card, display_finish)
    prices_by_finish: dict[str, dict[str, Any] | None] = {}
    for card_finish in available_finishes:
        prices_by_finish[card_finish] = price_to_json(display_price_for(conn, card, card_finish))
    cached_image = local_image_url(card["id"])
    return {
        "id": card["id"],
        "oracle_id": card.get("oracle_id"),
        "name": card.get("name"),
        "printed_name": card.get("printed_name"),
        "lang": card.get("lang"),
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "rarity": card.get("rarity"),
        "finishes": available_finishes,
        "available_finishes": available_finishes,
        "display_finish": display_finish,
        "prices_by_finish": prices_by_finish,
        "image_url": cached_image or image_url_for(card),
        "image_large_url": cached_image or large_image_url_for(card),
        "scryfall_uri": card.get("scryfall_uri"),
        "price": price_to_json(price),
    }


def price_to_json(price: PricePoint | None) -> dict[str, Any] | None:
    if price is None:
        return None
    return {
        "currency": price.currency,
        "finish": price.finish,
        "price": decimal_to_json(price.price),
        "source": price.source,
        "is_fallback": price.is_fallback,
    }


def add_collection_item(
    conn: sqlite3.Connection,
    *,
    scryfall_id: str,
    quantity: int,
    finish: str,
    condition: str,
    language: str | None,
    purchase_price: float | None,
    purchase_currency: str,
    purchase_date: str | None,
    notes: str | None,
) -> int:
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO collection_items (
            scryfall_id, quantity, finish, condition, language, purchase_price,
            purchase_currency, purchase_date, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scryfall_id,
            quantity,
            finish,
            condition,
            language,
            purchase_price,
            purchase_currency,
            purchase_date,
            notes,
            now,
            now,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def update_collection_item(conn: sqlite3.Connection, item_id: int, payload: dict[str, Any]) -> bool:
    allowed = {
        "quantity",
        "finish",
        "condition",
        "language",
        "purchase_price",
        "purchase_currency",
        "purchase_date",
        "notes",
    }
    updates = {key: payload[key] for key in allowed if key in payload}
    if not updates:
        return False

    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [item_id]
    cursor = conn.execute(
        f"UPDATE collection_items SET {assignments} WHERE id = ?",
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_collection_item(conn: sqlite3.Connection, item_id: int) -> bool:
    cursor = conn.execute("DELETE FROM collection_items WHERE id = ?", (item_id,))
    conn.commit()
    return cursor.rowcount > 0


def adjust_collection_quantity(
    conn: sqlite3.Connection,
    *,
    scryfall_id: str,
    finish: str,
    delta: int,
) -> dict[str, Any]:
    if delta == 0:
        raise ValueError("delta doit etre different de zero.")

    row = conn.execute(
        """
        SELECT id, quantity
        FROM collection_items
        WHERE scryfall_id = ? AND finish = ?
        """,
        (scryfall_id, finish),
    ).fetchone()

    if delta > 0:
        if row is None:
            item_id = add_collection_item(
                conn,
                scryfall_id=scryfall_id,
                quantity=delta,
                finish=finish,
                condition="near_mint",
                language=None,
                purchase_price=None,
                purchase_currency="EUR",
                purchase_date=None,
                notes=None,
            )
            return {"item_id": item_id, "quantity": delta, "deleted": False}

        quantity = int(row["quantity"]) + delta
        update_collection_item(conn, int(row["id"]), {"quantity": quantity})
        return {"item_id": int(row["id"]), "quantity": quantity, "deleted": False}

    if row is None:
        return {"item_id": None, "quantity": 0, "deleted": False}

    quantity = int(row["quantity"]) + delta
    item_id = int(row["id"])
    if quantity <= 0:
        delete_collection_item(conn, item_id)
        return {"item_id": item_id, "quantity": 0, "deleted": True}

    update_collection_item(conn, item_id, {"quantity": quantity})
    return {"item_id": item_id, "quantity": quantity, "deleted": False}


def summarize_collection_rows(
    conn: sqlite3.Connection,
    rows: Iterable[sqlite3.Row],
) -> dict[str, Any]:
    total_cards = 0
    value_with_duplicates = Decimal("0")
    value_without_duplicates = Decimal("0")
    unique_oracle: set[str] = set()
    unique_splash: set[str] = set()

    for row in rows:
        card = json.loads(row["raw_json"])
        scryfall_id = card.get("id") or row["scryfall_id"]
        quantity = int(row["quantity"])
        if quantity <= 0:
            continue
        price = display_price_for(conn, card, row["finish"])
        oracle_id = card.get("oracle_id") or scryfall_id
        if price is not None:
            value_with_duplicates += price.price * quantity
            value_without_duplicates += price.price
        total_cards += quantity
        unique_oracle.add(oracle_id)
        unique_splash.add(card.get("illustration_id") or scryfall_id)

    return {
        "total_cards": total_cards,
        "unique_cards": len(unique_oracle),
        "unique_splash": len(unique_splash),
        "estimated_value_eur": decimal_to_json(value_with_duplicates),
        "unique_value_eur": decimal_to_json(value_without_duplicates),
    }


def collection_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.quantity, ci.finish, ci.scryfall_id, c.raw_json
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        """
    ).fetchall()
    return {"summary": summarize_collection_rows(conn, rows)}


def list_collection(conn: sqlite3.Connection) -> dict[str, Any]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.*, c.raw_json
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        ORDER BY ci.updated_at DESC, ci.id DESC
        """
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        card = json.loads(row["raw_json"])
        quantity = int(row["quantity"])
        price = display_price_for(conn, card, row["finish"])
        line_value = Decimal("0")
        if price is not None:
            line_value = price.price * quantity

        items.append(
            {
                "id": row["id"],
                "quantity": quantity,
                "finish": row["finish"],
                "condition": row["condition"],
                "language": row["language"],
                "purchase_price": row["purchase_price"],
                "purchase_currency": row["purchase_currency"],
                "purchase_date": row["purchase_date"],
                "notes": row["notes"],
                "card": card_summary(conn, card, row["finish"]),
                "estimated_line_value": decimal_to_json(line_value),
            }
        )

    return {
        "summary": summarize_collection_rows(conn, rows),
        "items": items,
    }


def price_history(conn: sqlite3.Connection, scryfall_id: str, finish: str) -> list[dict[str, Any]]:
    chart_sources = tuple(meta["source"] for meta in CHART_PRICE_SOURCES.values())
    legacy_sources = chart_sources + ("scryfall-cardmarket", "mtgjson-cardmarket")
    placeholders = ",".join("?" for _ in legacy_sources)
    snapshots_table = catalog_table("price_snapshots")
    rows = conn.execute(
        f"""
        SELECT currency, finish, price, source, snapshot_date, collected_at
        FROM {snapshots_table}
        WHERE scryfall_id = ? AND finish = ? AND source IN ({placeholders})
        ORDER BY snapshot_date ASC, collected_at ASC
        """,
        (scryfall_id, finish, *legacy_sources),
    ).fetchall()
    snapshot_points = [
        {
            "currency": row["currency"],
            "finish": row["finish"],
            "price": row["price"],
            "source": row["source"],
            "snapshot_date": row["snapshot_date"],
            "collected_at": row["collected_at"],
        }
        for row in rows
    ]
    guide_points = cardmarket_guide_history_points(conn, scryfall_id, finish)
    for point in snapshot_points:
        if point["source"] == CARDMARKET_LEGACY_SOURCE:
            point["data_tier"] = "legacy"
        elif point["source"] == "scryfall-cardmarket":
            point["data_tier"] = "live"
        else:
            point["data_tier"] = "legacy"
    for point in guide_points:
        point["data_tier"] = "guide"
    if guide_points:
        return merge_cardmarket_history_points(guide_points, snapshot_points)
    return snapshot_points


def price_periods(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not history:
        return [
            {
                "key": key,
                "label": label_for_period(key),
                "available": False,
                "message": "Aucun snapshot disponible.",
            }
            for key in PRICE_PERIODS
        ]

    normalized = sorted(history, key=lambda point: point["snapshot_date"])
    latest = normalized[-1]
    latest_date = date.fromisoformat(latest["snapshot_date"])
    latest_price = Decimal(str(latest["price"]))

    periods: list[dict[str, Any]] = []
    for key, days in PRICE_PERIODS.items():
        cutoff = latest_date - timedelta(days=days)
        start = last_point_on_or_before(normalized, cutoff)
        if start is None:
            periods.append(
                {
                    "key": key,
                    "label": label_for_period(key),
                    "available": False,
                    "message": f"N/A: historique disponible depuis {normalized[0]['snapshot_date']} seulement.",
                    "first_available_date": normalized[0]["snapshot_date"],
                    "needed_date": cutoff.isoformat(),
                    "end_date": latest["snapshot_date"],
                    "end_price": decimal_to_json(latest_price),
                }
            )
            continue

        start_price = Decimal(str(start["price"]))
        absolute = latest_price - start_price
        percent = None
        if start_price != 0:
            percent = (absolute / start_price) * Decimal("100")

        periods.append(
            {
                "key": key,
                "label": label_for_period(key),
                "available": True,
                "start_date": start["snapshot_date"],
                "end_date": latest["snapshot_date"],
                "start_price": decimal_to_json(start_price),
                "end_price": decimal_to_json(latest_price),
                "absolute_change": decimal_to_json(absolute),
                "percent_change": decimal_to_json(percent),
                "uses_first_available": False,
            }
        )
    return periods


def last_point_on_or_before(history: list[dict[str, Any]], cutoff: date) -> dict[str, Any] | None:
    matching_point = None
    for point in history:
        if date.fromisoformat(point["snapshot_date"]) <= cutoff:
            matching_point = point
        else:
            break
    return matching_point


def label_for_period(key: str) -> str:
    return {
        "1d": "1 jour",
        "1m": "1 mois",
        "6m": "6 mois",
        "1y": "1 an",
        "5y": "5 ans",
    }[key]


def collection_quantities_for_card(conn: sqlite3.Connection, scryfall_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT finish, SUM(quantity) AS quantity
        FROM collection_items
        WHERE scryfall_id = ?
        GROUP BY finish
        """,
        (scryfall_id,),
    ).fetchall()
    return {row["finish"]: int(row["quantity"]) for row in rows}


def owned_counts_by_card_finish(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    rows = conn.execute(
        """
        SELECT scryfall_id, finish, SUM(quantity) AS quantity
        FROM collection_items
        WHERE quantity > 0
        GROUP BY scryfall_id, finish
        """
    ).fetchall()
    return {(row["scryfall_id"], row["finish"]): int(row["quantity"]) for row in rows}


def finish_breakdown_for_scryfall(
    owned_by_finish: dict[tuple[str, str], int],
    scryfall_id: str | None,
) -> dict[str, int]:
    if not scryfall_id:
        return {}
    breakdown: dict[str, int] = {}
    for finish in ("nonfoil", "foil", "etched"):
        qty = owned_by_finish.get((scryfall_id, finish), 0)
        if qty > 0:
            breakdown[finish] = qty
    return breakdown


def oracle_collection_summary(conn: sqlite3.Connection, oracle_id: str | None) -> dict[str, Any] | None:
    if not oracle_id:
        return None
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.scryfall_id, ci.finish, SUM(ci.quantity) AS quantity
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE c.oracle_id = ? AND ci.quantity > 0
        GROUP BY ci.scryfall_id, ci.finish
        """,
        (oracle_id,),
    ).fetchall()
    if not rows:
        return {"total_copies": 0, "printing_count": 0, "by_finish": {}}
    by_finish: dict[str, int] = {}
    printing_ids: set[str] = set()
    for row in rows:
        printing_ids.add(row["scryfall_id"])
        finish = str(row["finish"])
        by_finish[finish] = by_finish.get(finish, 0) + int(row["quantity"])
    return {
        "total_copies": sum(by_finish.values()),
        "printing_count": len(printing_ids),
        "by_finish": by_finish,
    }


def collection_card_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT scryfall_id FROM collection_items ORDER BY scryfall_id"
    ).fetchall()
    return [row["scryfall_id"] for row in rows]


def backfill_owned_decks_from_imports(conn: sqlite3.Connection) -> int:
    from .local_cache import load_deck_list

    backfill_key = "owned_decks_import_backfill_v1"
    if get_app_metadata(conn, backfill_key) == "1":
        return 0

    rows = conn.execute(
        "SELECT DISTINCT notes FROM collection_items WHERE notes LIKE 'Import precon:%'"
    ).fetchall()
    prefix = "Import precon: "
    import_names = {
        (row["notes"] or "")[len(prefix):]
        for row in rows
        if (row["notes"] or "").startswith(prefix)
    }
    if not import_names:
        set_app_metadata(conn, backfill_key, "1")
        return 0

    added = 0
    for deck in load_deck_list():
        file_name = deck.get("fileName") or ""
        if not file_name or is_deck_owned(conn, file_name) or is_deck_owned_dismissed(conn, file_name):
            continue
        if (deck.get("name") or "") in import_names:
            set_deck_owned(conn, file_name, True)
            added += 1
    set_app_metadata(conn, backfill_key, "1")
    return added


def is_deck_owned_dismissed(conn: sqlite3.Connection, file_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM owned_deck_dismissals WHERE file_name = ?",
        (file_name,),
    ).fetchone()
    return row is not None


def owned_deck_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT file_name FROM owned_decks").fetchall()
    return {row["file_name"] for row in rows}


def is_deck_owned(conn: sqlite3.Connection, file_name: str) -> bool:
    row = conn.execute("SELECT 1 FROM owned_decks WHERE file_name = ?", (file_name,)).fetchone()
    return row is not None


def set_deck_owned(conn: sqlite3.Connection, file_name: str, owned: bool) -> bool:
    if owned:
        conn.execute("DELETE FROM owned_deck_dismissals WHERE file_name = ?", (file_name,))
        conn.execute(
            """
            INSERT INTO owned_decks (file_name, owned_at)
            VALUES (?, ?)
            ON CONFLICT(file_name) DO UPDATE SET owned_at = excluded.owned_at
            """,
            (file_name, utc_now()),
        )
    else:
        conn.execute("DELETE FROM owned_decks WHERE file_name = ?", (file_name,))
        conn.execute(
            """
            INSERT INTO owned_deck_dismissals (file_name, dismissed_at)
            VALUES (?, ?)
            ON CONFLICT(file_name) DO UPDATE SET dismissed_at = excluded.dismissed_at
            """,
            (file_name, utc_now()),
        )
    conn.commit()
    return owned


def get_app_metadata(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_metadata WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return row["value"]


def set_app_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_metadata (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, utc_now()),
    )
    conn.commit()


def tracked_mtgjson_cards(conn: sqlite3.Connection) -> list[dict[str, str]]:
    map_table = catalog_table("mtgjson_card_map")
    rows = conn.execute(
        f"""
        SELECT scryfall_id, mtgjson_uuid
        FROM {map_table}
        ORDER BY scryfall_id
        """
    ).fetchall()
    return [{"scryfall_id": row["scryfall_id"], "mtgjson_uuid": row["mtgjson_uuid"]} for row in rows]


def tracked_mtgjson_set_codes(conn: sqlite3.Connection) -> list[str]:
    map_table = catalog_table("mtgjson_card_map")
    rows = conn.execute(
        f"""
        SELECT DISTINCT set_code
        FROM {map_table}
        WHERE set_code IS NOT NULL AND TRIM(set_code) != ''
        ORDER BY set_code
        """
    ).fetchall()
    return [row["set_code"] for row in rows]


def save_cardmarket_product_mappings(
    conn: sqlite3.Connection,
    mappings: Iterable[dict[str, Any]],
) -> int:
    map_table = catalog_table("cardmarket_product_map")
    now = utc_now()
    rows = [
        (
            mapping["id_product"],
            mapping["scryfall_id"],
            mapping.get("set_code"),
            mapping.get("collector_number"),
            now,
        )
        for mapping in mappings
    ]
    if not rows:
        return 0
    conn.executemany(
        f"""
        INSERT INTO {map_table} (
            id_product, scryfall_id, set_code, collector_number, mapped_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id_product) DO UPDATE SET
            scryfall_id = excluded.scryfall_id,
            set_code = excluded.set_code,
            collector_number = excluded.collector_number,
            mapped_at = excluded.mapped_at
        """,
        rows,
    )
    return len(rows)


def cardmarket_product_id_by_scryfall(
    conn: sqlite3.Connection,
    scryfall_ids: Iterable[str],
) -> dict[str, int]:
    ids = list(dict.fromkeys(scryfall_ids))
    if not ids:
        return {}
    map_table = catalog_table("cardmarket_product_map")
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT scryfall_id, id_product
        FROM {map_table}
        WHERE scryfall_id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {row["scryfall_id"]: row["id_product"] for row in rows}


def save_cardmarket_price_guide_daily(
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, Any]],
) -> int:
    guide_table = catalog_table("cardmarket_price_guide_daily")
    sql = f"""
        INSERT INTO {guide_table} (
            id_product, snapshot_date, trend, low_price, avg, avg1, avg7, avg30,
            trend_foil, low_foil, avg_foil, avg1_foil, avg7_foil, avg30_foil,
            guide_version, guide_created_at, collected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_product, snapshot_date) DO UPDATE SET
            trend = excluded.trend,
            low_price = excluded.low_price,
            avg = excluded.avg,
            avg1 = excluded.avg1,
            avg7 = excluded.avg7,
            avg30 = excluded.avg30,
            trend_foil = excluded.trend_foil,
            low_foil = excluded.low_foil,
            avg_foil = excluded.avg_foil,
            avg1_foil = excluded.avg1_foil,
            avg7_foil = excluded.avg7_foil,
            avg30_foil = excluded.avg30_foil,
            guide_version = excluded.guide_version,
            guide_created_at = excluded.guide_created_at,
            collected_at = excluded.collected_at
    """
    payload = [
        (
            row["id_product"],
            row["snapshot_date"],
            row.get("trend"),
            row.get("low_price"),
            row.get("avg"),
            row.get("avg1"),
            row.get("avg7"),
            row.get("avg30"),
            row.get("trend_foil"),
            row.get("low_foil"),
            row.get("avg_foil"),
            row.get("avg1_foil"),
            row.get("avg7_foil"),
            row.get("avg30_foil"),
            row.get("guide_version"),
            row.get("guide_created_at"),
            row["collected_at"],
        )
        for row in rows
    ]
    if not payload:
        return 0
    conn.executemany(sql, payload)
    return len(payload)


CARDMARKET_GUIDE_SOURCE = "cardmarket-guide"
CARDMARKET_LEGACY_SOURCE = "mtgjson-cardmarket"
CARDMARKET_GUIDE_FINISH_COLUMNS = {
    "nonfoil": {
        "chart": "trend",
        "low": "low_price",
        "avg": "avg",
        "avg1": "avg1",
        "avg7": "avg7",
        "avg30": "avg30",
    },
    "foil": {
        "chart": "trend_foil",
        "low": "low_foil",
        "avg": "avg_foil",
        "avg1": "avg1_foil",
        "avg7": "avg7_foil",
        "avg30": "avg30_foil",
    },
    "etched": {
        "chart": "trend",
        "low": "low_price",
        "avg": "avg",
        "avg1": "avg1",
        "avg7": "avg7",
        "avg30": "avg30",
    },
}


def cardmarket_guide_columns(finish: str) -> dict[str, str]:
    return CARDMARKET_GUIDE_FINISH_COLUMNS.get(finish) or CARDMARKET_GUIDE_FINISH_COLUMNS["nonfoil"]


def cardmarket_guide_chart_price(row: sqlite3.Row | dict[str, Any], finish: str) -> float | None:
    columns = cardmarket_guide_columns(finish)
    value = row[columns["chart"]] if isinstance(row, dict) else row[columns["chart"]]
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def cardmarket_guide_row_metrics(row: sqlite3.Row | dict[str, Any], finish: str) -> dict[str, float | None]:
    columns = cardmarket_guide_columns(finish)

    def metric(key: str) -> float | None:
        column = columns.get(key)
        if not column:
            return None
        raw = row[column] if isinstance(row, dict) else row[column]
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "trend": metric("chart"),
        "low": metric("low"),
        "avg": metric("avg"),
        "avg1": metric("avg1"),
        "avg7": metric("avg7"),
        "avg30": metric("avg30"),
    }


def cardmarket_guide_history_points(
    conn: sqlite3.Connection,
    scryfall_id: str,
    finish: str,
) -> list[dict[str, Any]]:
    columns = cardmarket_guide_columns(finish)
    chart_column = columns["chart"]
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    rows = conn.execute(
        f"""
        SELECT g.snapshot_date, g.collected_at, g.{chart_column} AS chart_price
        FROM {guide_table} g
        INNER JOIN {map_table} m ON m.id_product = g.id_product
        WHERE m.scryfall_id = ?
          AND g.{chart_column} IS NOT NULL
          AND g.{chart_column} > 0
        ORDER BY g.snapshot_date ASC, g.collected_at ASC
        """,
        (scryfall_id,),
    ).fetchall()
    return [
        {
            "currency": "EUR",
            "finish": finish,
            "price": float(row["chart_price"]),
            "source": CARDMARKET_GUIDE_SOURCE,
            "snapshot_date": row["snapshot_date"],
            "collected_at": row["collected_at"],
        }
        for row in rows
    ]


def cardmarket_guide_bulk_history_points(
    conn: sqlite3.Connection,
    scryfall_ids: list[str],
) -> list[dict[str, Any]]:
    if not scryfall_ids:
        return []
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    points: list[dict[str, Any]] = []
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT m.scryfall_id, g.snapshot_date, g.collected_at,
                   g.trend, g.low_price, g.avg, g.avg1, g.avg7, g.avg30,
                   g.trend_foil, g.low_foil, g.avg_foil, g.avg1_foil, g.avg7_foil, g.avg30_foil
            FROM {guide_table} g
            INNER JOIN {map_table} m ON m.id_product = g.id_product
            WHERE m.scryfall_id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        for row in rows:
            for finish in ("nonfoil", "foil"):
                price = cardmarket_guide_chart_price(row, finish)
                if price is None:
                    continue
                points.append(
                    {
                        "scryfall_id": row["scryfall_id"],
                        "finish": finish,
                        "snapshot_date": row["snapshot_date"],
                        "price": price,
                        "source": CARDMARKET_GUIDE_SOURCE,
                        "currency": "EUR",
                        "collected_at": row["collected_at"],
                    }
                )
    return points


def cardmarket_latest_guide_for_card(
    conn: sqlite3.Connection,
    scryfall_id: str,
    finish: str,
) -> dict[str, Any] | None:
    columns = cardmarket_guide_columns(finish)
    chart_column = columns["chart"]
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    row = conn.execute(
        f"""
        SELECT g.*, m.id_product
        FROM {guide_table} g
        INNER JOIN {map_table} m ON m.id_product = g.id_product
        WHERE m.scryfall_id = ?
          AND g.{chart_column} IS NOT NULL
          AND g.{chart_column} > 0
        ORDER BY g.snapshot_date DESC, g.collected_at DESC
        LIMIT 1
        """,
        (scryfall_id,),
    ).fetchone()
    if row is None:
        return None
    metrics = cardmarket_guide_row_metrics(row, finish)
    return {
        "id_product": int(row["id_product"]),
        "snapshot_date": row["snapshot_date"],
        "collected_at": row["collected_at"],
        "metrics": metrics,
    }


def batch_cardmarket_latest_guide(
    conn: sqlite3.Connection,
    scryfall_ids: list[str],
    *,
    finish: str = "nonfoil",
) -> dict[str, dict[str, Any]]:
    if not scryfall_ids:
        return {}
    columns = cardmarket_guide_columns(finish)
    chart_column = columns["chart"]
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    stats: dict[str, dict[str, Any]] = {}
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT m.scryfall_id, g.*, m.id_product
            FROM {guide_table} g
            INNER JOIN {map_table} m ON m.id_product = g.id_product
            INNER JOIN (
                SELECT m2.scryfall_id, MAX(g2.snapshot_date) AS snapshot_date
                FROM {guide_table} g2
                INNER JOIN {map_table} m2 ON m2.id_product = g2.id_product
                WHERE m2.scryfall_id IN ({placeholders})
                  AND g2.{chart_column} IS NOT NULL
                  AND g2.{chart_column} > 0
                GROUP BY m2.scryfall_id
            ) latest ON latest.scryfall_id = m.scryfall_id AND latest.snapshot_date = g.snapshot_date
            WHERE m.scryfall_id IN ({placeholders})
            """,
            (*chunk, *chunk),
        ).fetchall()
        for row in rows:
            stats[row["scryfall_id"]] = {
                "id_product": int(row["id_product"]),
                "snapshot_date": row["snapshot_date"],
                "metrics": cardmarket_guide_row_metrics(row, finish),
            }
    return stats


def cardmarket_guide_period_bounds(
    conn: sqlite3.Connection,
    range_key: str,
) -> tuple[str, str] | None:
    chart_range_days = {"7d": 7, "1m": 30, "6m": 183, "1y": 365, "5y": 1825}
    guide_table = catalog_table("cardmarket_price_guide_daily")
    latest_row = conn.execute(
        f"SELECT MAX(snapshot_date) AS latest_date FROM {guide_table}"
    ).fetchone()
    if latest_row is None or not latest_row["latest_date"]:
        return None
    latest_date = date.fromisoformat(latest_row["latest_date"])
    chart_days = chart_range_days.get(range_key, 7)
    cutoff = (latest_date - timedelta(days=chart_days)).isoformat()
    first_row = conn.execute(
        f"""
        SELECT MIN(snapshot_date) AS start_date
        FROM {guide_table}
        WHERE snapshot_date >= ?
        """,
        (cutoff,),
    ).fetchone()
    if first_row is None or not first_row["start_date"]:
        return latest_row["latest_date"], latest_row["latest_date"]
    return first_row["start_date"], latest_row["latest_date"]


def cardmarket_guide_pre_period_stats(
    conn: sqlite3.Connection,
    scryfall_ids: list[str],
    *,
    before_date: str,
    lookback_days: int,
    finish: str = "nonfoil",
) -> dict[str, dict[str, float]]:
    if not scryfall_ids:
        return {}
    try:
        cutoff_date = (date.fromisoformat(before_date) - timedelta(days=lookback_days)).isoformat()
    except ValueError:
        return {}
    columns = cardmarket_guide_columns(finish)
    chart_column = columns["chart"]
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    stats: dict[str, dict[str, float]] = {}
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT m.scryfall_id,
                   MIN(g.{chart_column}) AS min_price,
                   MAX(g.{chart_column}) AS max_price,
                   AVG(g.{chart_column}) AS avg_price,
                   COUNT(*) AS point_count
            FROM {guide_table} g
            INNER JOIN {map_table} m ON m.id_product = g.id_product
            WHERE m.scryfall_id IN ({placeholders})
              AND g.snapshot_date < ?
              AND g.snapshot_date >= ?
              AND g.{chart_column} IS NOT NULL
              AND g.{chart_column} > 0
            GROUP BY m.scryfall_id
            """,
            (*chunk, before_date, cutoff_date),
        ).fetchall()
        for row in rows:
            stats[row["scryfall_id"]] = {
                "min_price": float(row["min_price"]),
                "max_price": float(row["max_price"]),
                "avg_price": float(row["avg_price"] or 0),
                "point_count": float(row["point_count"]),
            }
    return stats


def merge_cardmarket_history_points(
    guide_points: list[dict[str, Any]],
    snapshot_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dates_with_guide = {point["snapshot_date"] for point in guide_points}
    merged = list(guide_points)
    for point in snapshot_points:
        if point["snapshot_date"] in dates_with_guide:
            continue
        merged.append(point)
    merged.sort(key=lambda point: (point["snapshot_date"], point.get("collected_at") or ""))
    return merged


def cardmarket_guide_multi_series(
    conn: sqlite3.Connection,
    scryfall_id: str,
    finish: str,
) -> dict[str, list[dict[str, Any]]]:
    columns = cardmarket_guide_columns(finish)
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    metric_columns = {
        "trend": columns["chart"],
        "low": columns["low"],
        "avg7": columns["avg7"],
    }
    select_sql = ", ".join(f"g.{column} AS {alias}" for alias, column in metric_columns.items())
    rows = conn.execute(
        f"""
        SELECT g.snapshot_date, g.collected_at, {select_sql}
        FROM {guide_table} g
        INNER JOIN {map_table} m ON m.id_product = g.id_product
        WHERE m.scryfall_id = ?
        ORDER BY g.snapshot_date ASC
        """,
        (scryfall_id,),
    ).fetchall()
    series: dict[str, list[dict[str, Any]]] = {key: [] for key in metric_columns}
    for row in rows:
        for alias in metric_columns:
            value = row[alias]
            if value is None or float(value) <= 0:
                continue
            series[alias].append(
                {
                    "currency": "EUR",
                    "finish": finish,
                    "price": float(value),
                    "metric": alias,
                    "source": CARDMARKET_GUIDE_SOURCE,
                    "snapshot_date": row["snapshot_date"],
                    "collected_at": row["collected_at"],
                    "data_tier": "guide",
                }
            )
    return series


def cardmarket_mapping_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    mtg_map = catalog_table("mtgjson_card_map")
    mapped_row = conn.execute(f"SELECT COUNT(*) AS count FROM {map_table}").fetchone()
    tracked_row = conn.execute(f"SELECT COUNT(*) AS count FROM {mtg_map}").fetchone()
    guide_bounds = conn.execute(
        f"SELECT MIN(snapshot_date) AS start_date, MAX(snapshot_date) AS end_date, COUNT(*) AS rows FROM {guide_table}"
    ).fetchone()
    mapped = int(mapped_row["count"] if mapped_row else 0)
    tracked = int(tracked_row["count"] if tracked_row else 0)
    coverage = (mapped / tracked) if tracked else None
    return {
        "products_mapped": mapped,
        "cards_tracked_mtgjson": tracked,
        "mapping_coverage": coverage,
        "mapping_low": coverage is not None and coverage < 0.9,
        "guide_start_date": guide_bounds["start_date"] if guide_bounds else None,
        "guide_end_date": guide_bounds["end_date"] if guide_bounds else None,
        "guide_rows": int(guide_bounds["rows"] or 0) if guide_bounds else 0,
    }
