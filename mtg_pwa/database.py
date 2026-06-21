from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .prices import PricePoint, current_eur_price, decimal_to_json, extract_eur_prices


DEFAULT_DB_PATH = Path("data/mtg_pwa.sqlite3")
PRICE_PERIODS = {
    "1d": 1,
    "1m": 30,
    "6m": 183,
    "1y": 365,
    "5y": 1825,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
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
            updated_at TEXT NOT NULL,
            FOREIGN KEY (scryfall_id) REFERENCES cards(scryfall_id)
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

        CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
        CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON cards(oracle_id);
        CREATE INDEX IF NOT EXISTS idx_collection_card ON collection_items(scryfall_id);
        CREATE INDEX IF NOT EXISTS idx_price_card_finish ON price_snapshots(scryfall_id, finish, currency, snapshot_date);
        """
    )
    conn.commit()


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
    conn.execute(
        """
        INSERT INTO cards (
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
        conn.execute(
            """
            INSERT INTO price_snapshots (
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
    conn.execute(
        """
        INSERT INTO price_snapshots (
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
    saved = 0
    for point in points:
        conn.execute(
            """
            INSERT INTO price_snapshots (
                scryfall_id, currency, finish, price, source, snapshot_date,
                collected_at, source_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scryfall_id, currency, finish, source, snapshot_date)
            DO UPDATE SET
                price = excluded.price,
                collected_at = excluded.collected_at
            """,
            (
                point["scryfall_id"],
                point["currency"],
                point["finish"],
                point["price"],
                point["source"],
                point["snapshot_date"],
                point["collected_at"],
                point.get("source_updated_at"),
            ),
        )
        saved += 1
    return saved


def cached_mtgjson_uuid(conn: sqlite3.Connection, scryfall_id: str) -> str | None:
    row = conn.execute(
        "SELECT mtgjson_uuid FROM mtgjson_card_map WHERE scryfall_id = ?",
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
    conn.execute(
        """
        INSERT INTO mtgjson_card_map (
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
    row = conn.execute(
        "SELECT raw_json FROM mtgjson_price_cache WHERE mtgjson_uuid = ?",
        (mtgjson_uuid,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["raw_json"])


def save_mtgjson_price_entry(conn: sqlite3.Connection, mtgjson_uuid: str, price_entry: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO mtgjson_price_cache (mtgjson_uuid, raw_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(mtgjson_uuid) DO UPDATE SET
            raw_json = excluded.raw_json,
            fetched_at = excluded.fetched_at
        """,
        (mtgjson_uuid, json.dumps(price_entry, ensure_ascii=False), utc_now()),
    )


def get_cached_card(conn: sqlite3.Connection, scryfall_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT raw_json FROM cards WHERE scryfall_id = ?",
        (scryfall_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["raw_json"])


def latest_snapshot(
    conn: sqlite3.Connection,
    scryfall_id: str,
    finish: str,
    currency: str = "EUR",
) -> PricePoint | None:
    row = conn.execute(
        """
        SELECT price, source
        FROM price_snapshots
        WHERE scryfall_id = ? AND finish = ? AND currency = ?
        ORDER BY snapshot_date DESC, collected_at DESC
        LIMIT 1
        """,
        (scryfall_id, finish, currency),
    ).fetchone()
    if row is None:
        return None
    return PricePoint(
        currency=currency,
        finish=finish,
        price=Decimal(str(row["price"])),
        source=row["source"],
        is_fallback=True,
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
    available_finishes = [value for value in card.get("finishes") or [] if value in {"nonfoil", "foil", "etched"}]
    display_finish = finish
    if available_finishes and finish not in available_finishes:
        display_finish = available_finishes[0]
    price = display_price_for(conn, card, display_finish)
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
        "finishes": card.get("finishes") or [],
        "display_finish": display_finish,
        "image_url": image_url_for(card),
        "image_large_url": large_image_url_for(card),
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


def list_collection(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT ci.*, c.raw_json
        FROM collection_items ci
        JOIN cards c ON c.scryfall_id = ci.scryfall_id
        ORDER BY ci.updated_at DESC, ci.id DESC
        """
    ).fetchall()

    items: list[dict[str, Any]] = []
    total_cards = 0
    estimated_value = Decimal("0")
    unique_cards: set[str] = set()

    for row in rows:
        card = json.loads(row["raw_json"])
        quantity = int(row["quantity"])
        price = display_price_for(conn, card, row["finish"])
        line_value = Decimal("0")
        if price is not None:
            line_value = price.price * quantity
            estimated_value += line_value

        total_cards += quantity
        unique_cards.add(row["scryfall_id"])

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
        "summary": {
            "total_cards": total_cards,
            "unique_cards": len(unique_cards),
            "estimated_value_eur": decimal_to_json(estimated_value),
        },
        "items": items,
    }


def price_history(conn: sqlite3.Connection, scryfall_id: str, finish: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT currency, finish, price, source, snapshot_date, collected_at
        FROM price_snapshots
        WHERE scryfall_id = ? AND finish = ? AND currency = 'EUR'
        ORDER BY snapshot_date ASC, collected_at ASC
        """,
        (scryfall_id, finish),
    ).fetchall()
    return [
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


def collection_card_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT scryfall_id FROM collection_items ORDER BY scryfall_id"
    ).fetchall()
    return [row["scryfall_id"] for row in rows]
