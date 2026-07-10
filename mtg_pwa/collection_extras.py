from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .collection_index import ensure_collection_app_tables
from .database import (
    catalog_table,
    collection_card_ids,
    decimal_to_json,
    display_price_for,
    get_cached_card,
    utc_now,
)
from .local_cache import catalog_image_url
from .sets_catalog import set_cards


def list_wishlist(conn) -> list[dict[str, Any]]:
    ensure_collection_app_tables(conn)
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT w.*, c.name, c.set_code, c.set_name, c.raw_json
        FROM wishlist_items w
        LEFT JOIN {cards_table} c ON c.scryfall_id = w.scryfall_id
        ORDER BY w.priority DESC, w.updated_at DESC, w.id DESC
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        card = json.loads(row["raw_json"]) if row["raw_json"] else None
        price = display_price_for(conn, card, row["finish"]) if card else None
        unit_price = float(price.price) if price else None
        max_price = float(row["max_price_eur"]) if row["max_price_eur"] is not None else None
        budget_gap = None
        under_max = None
        if unit_price is not None and max_price is not None:
            budget_gap = round(max_price - unit_price, 2)
            under_max = unit_price <= max_price
        items.append(
            {
                "id": row["id"],
                "scryfall_id": row["scryfall_id"],
                "finish": row["finish"],
                "quantity": int(row["quantity"]),
                "priority": int(row["priority"]),
                "max_price_eur": row["max_price_eur"],
                "notes": row["notes"],
                "name": row["name"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "collector_number": card.get("collector_number") if card else None,
                "image_url": catalog_image_url(row["scryfall_id"]),
                "unit_price_eur": unit_price,
                "budget_gap_eur": budget_gap,
                "under_max": under_max,
            }
        )
    return items


def upsert_wishlist_item(
    conn,
    *,
    scryfall_id: str,
    finish: str = "nonfoil",
    quantity: int = 1,
    priority: int = 0,
    max_price_eur: float | None = None,
    notes: str | None = None,
    auto_alert: bool = False,
) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO wishlist_items (
            scryfall_id, finish, quantity, priority, max_price_eur, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scryfall_id, finish) DO UPDATE SET
            quantity = excluded.quantity,
            priority = excluded.priority,
            max_price_eur = excluded.max_price_eur,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (scryfall_id, finish, quantity, priority, max_price_eur, notes, now, now),
    )
    alert_id = None
    if auto_alert and max_price_eur is not None:
        alert = create_price_alert(
            conn,
            scryfall_id=scryfall_id,
            finish=finish,
            direction="below",
            threshold_eur=float(max_price_eur),
        )
        alert_id = alert.get("id")
    conn.commit()
    return {
        "scryfall_id": scryfall_id,
        "finish": finish,
        "quantity": quantity,
        "alert_id": alert_id,
    }


def delete_wishlist_item(conn, item_id: int) -> None:
    ensure_collection_app_tables(conn)
    conn.execute("DELETE FROM wishlist_items WHERE id = ?", (item_id,))
    conn.commit()


def list_price_alerts(conn) -> list[dict[str, Any]]:
    ensure_collection_app_tables(conn)
    rows = conn.execute(
        "SELECT * FROM price_alerts WHERE active = 1 ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def create_price_alert(
    conn,
    *,
    scryfall_id: str,
    finish: str,
    direction: str,
    threshold_eur: float,
    source: str = "cardmarket",
) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO price_alerts (
            scryfall_id, finish, direction, threshold_eur, active, source, created_at
        )
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (scryfall_id, finish, direction, threshold_eur, source, now),
    )
    conn.commit()
    return {"id": cursor.lastrowid, "scryfall_id": scryfall_id, "threshold_eur": threshold_eur}


def delete_price_alert(conn, alert_id: int) -> None:
    ensure_collection_app_tables(conn)
    conn.execute("DELETE FROM price_alerts WHERE id = ?", (alert_id,))
    conn.commit()


def export_collection_csv(conn) -> str:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.scryfall_id, ci.finish, ci.quantity, ci.condition, ci.language,
               c.name, c.set_code, c.collector_number
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
        ORDER BY c.set_code, c.collector_number, ci.finish
        """
    ).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["scryfall_id", "name", "set_code", "collector_number", "finish", "quantity", "condition", "language"])
    for row in rows:
        writer.writerow(
            [
                row["scryfall_id"],
                row["name"],
                row["set_code"],
                row["collector_number"],
                row["finish"],
                row["quantity"],
                row["condition"],
                row["language"] or "",
            ]
        )
    return buffer.getvalue()


def import_collection_csv(conn, raw_text: str) -> dict[str, int]:
    from .database import adjust_collection_quantity

    reader = csv.DictReader(io.StringIO(raw_text))
    imported = 0
    skipped = 0
    for row in reader:
        scryfall_id = (row.get("scryfall_id") or "").strip()
        if not scryfall_id:
            skipped += 1
            continue
        finish = (row.get("finish") or "nonfoil").strip().lower()
        try:
            quantity = int(row.get("quantity") or "0")
        except ValueError:
            skipped += 1
            continue
        if quantity <= 0:
            skipped += 1
            continue
        adjust_collection_quantity(conn, scryfall_id=scryfall_id, finish=finish, delta=quantity)
        imported += 1
    conn.commit()
    return {"imported": imported, "skipped": skipped}


def oracle_collection_view(conn, oracle_id: str) -> dict[str, Any]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.finish, ci.quantity, c.scryfall_id, c.name, c.set_code, c.set_name,
               c.collector_number, c.raw_json
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0 AND c.oracle_id = ?
        ORDER BY c.set_code, c.collector_number
        """,
        (oracle_id,),
    ).fetchall()
    prints: list[dict[str, Any]] = []
    total_qty = 0
    total_value = Decimal("0")
    for row in rows:
        card = json.loads(row["raw_json"])
        qty = int(row["quantity"])
        price = display_price_for(conn, card, row["finish"])
        unit = price.price if price else Decimal("0")
        total_qty += qty
        total_value += unit * qty
        prints.append(
            {
                "scryfall_id": row["scryfall_id"],
                "name": row["name"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "number": row["collector_number"],
                "finish": row["finish"],
                "quantity": qty,
                "unit_price_eur": float(unit) if price else None,
            }
        )
    return {
        "oracle_id": oracle_id,
        "total_quantity": total_qty,
        "total_value_eur": decimal_to_json(total_value),
        "prints": prints,
    }


def missing_cards_for_set(conn, set_code: str, *, display_lang: str = "fr") -> dict[str, Any]:
    payload = set_cards(set_code, display_lang=display_lang)
    missing = [card for card in payload.get("cards") or [] if not card.get("owned")]
    total_cost = Decimal("0")
    priced_count = 0
    enriched: list[dict[str, Any]] = []
    for card in missing:
        unit = card.get("unit_price_eur")
        if unit is not None:
            priced_count += 1
            total_cost += Decimal(str(unit))
        enriched.append(card)
    return {
        "set_code": payload.get("set_code"),
        "set_name": payload.get("set_name"),
        "missing_count": len(missing),
        "owned_unique": payload.get("summary", {}).get("owned_unique", 0),
        "total_cards": payload.get("summary", {}).get("total_cards", 0),
        "estimated_cost_eur": decimal_to_json(total_cost),
        "priced_missing_count": priced_count,
        "cards": enriched,
    }


def collection_issues(conn) -> dict[str, Any]:
    cards_table = catalog_table("cards")
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    duplicates = conn.execute(
        """
        SELECT scryfall_id, finish, COUNT(*) AS rows_count, SUM(quantity) AS total_qty
        FROM collection_items
        WHERE quantity > 0
        GROUP BY scryfall_id, finish
        HAVING rows_count > 1
        """
    ).fetchall()
    stale_rows = conn.execute(
        f"""
        SELECT ci.scryfall_id, ci.finish, ci.quantity, c.name, c.set_code
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
          AND NOT EXISTS (
            SELECT 1 FROM {catalog_table("price_daily")} pd
            WHERE pd.scryfall_id = ci.scryfall_id
              AND pd.snapshot_date >= ?
              AND (
                pd.sf_cm_nonfoil IS NOT NULL OR pd.sf_cm_foil IS NOT NULL OR pd.sf_cm_etched IS NOT NULL
              )
          )
        LIMIT 200
        """
        ,
        (cutoff,),
    ).fetchall()
    return {
        "duplicate_lines": [dict(row) for row in duplicates],
        "stale_price_cards": [dict(row) for row in stale_rows],
    }


def portfolio_stats(conn) -> dict[str, Any]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.quantity, ci.finish, c.raw_json, c.rarity, c.set_code
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
        """
    ).fetchall()
    by_rarity: dict[str, int] = {}
    by_set: dict[str, int] = {}
    by_color: dict[str, int] = {}
    total_cards = 0
    for row in rows:
        card = json.loads(row["raw_json"])
        qty = int(row["quantity"])
        total_cards += qty
        rarity = (card.get("rarity") or "unknown").lower()
        by_rarity[rarity] = by_rarity.get(rarity, 0) + qty
        set_code = (card.get("set") or row["set_code"] or "?").upper()
        by_set[set_code] = by_set.get(set_code, 0) + qty
        colors = card.get("colors") or []
        if not colors:
            by_color["C"] = by_color.get("C", 0) + qty
        else:
            for color in colors:
                by_color[color] = by_color.get(color, 0) + qty
    top_sets = sorted(by_set.items(), key=lambda entry: entry[1], reverse=True)[:12]
    return {
        "total_cards": total_cards,
        "by_rarity": by_rarity,
        "by_color": by_color,
        "top_sets": [{"set_code": code, "quantity": qty} for code, qty in top_sets],
    }


def cardmarket_archive_status(conn) -> dict[str, Any]:
    guide_table = catalog_table("cardmarket_price_guide_daily")
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT snapshot_date) AS days,
               MIN(snapshot_date) AS first_date,
               MAX(snapshot_date) AS last_date
        FROM {guide_table}
        """
    ).fetchone()
    days = int(row["days"] or 0)
    last_date = row["last_date"]
    lag_days = 0
    if last_date:
        lag_days = max(0, (date.today() - date.fromisoformat(last_date)).days)
    return {
        "archive_days": days,
        "first_date": row["first_date"],
        "last_date": last_date,
        "lag_days": lag_days,
        "healthy": days >= 7 and lag_days <= 1,
    }


def owned_scryfall_id_set(conn) -> set[str]:
    return set(collection_card_ids(conn))


def wishlist_scryfall_id_set(conn) -> set[str]:
    ensure_collection_app_tables(conn)
    rows = conn.execute("SELECT DISTINCT scryfall_id FROM wishlist_items").fetchall()
    return {row["scryfall_id"] for row in rows}


def list_binder_slots(conn, *, binder_name: str = "Principal") -> list[dict[str, Any]]:
    ensure_collection_app_tables(conn)
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT b.*, c.name, c.set_code, c.set_name, c.raw_json
        FROM binder_slots b
        LEFT JOIN {cards_table} c ON c.scryfall_id = b.scryfall_id
        WHERE b.binder_name = ?
        ORDER BY b.page_number, b.slot_number, b.id
        """,
        (binder_name,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        card = json.loads(row["raw_json"]) if row["raw_json"] else None
        price = display_price_for(conn, card, row["finish"]) if card else None
        items.append(
            {
                "id": row["id"],
                "binder_name": row["binder_name"],
                "page_number": int(row["page_number"]),
                "slot_number": int(row["slot_number"]),
                "scryfall_id": row["scryfall_id"],
                "finish": row["finish"],
                "condition": row["condition"],
                "quantity": int(row["quantity"]),
                "notes": row["notes"],
                "name": row["name"],
                "set_code": row["set_code"],
                "image_url": catalog_image_url(row["scryfall_id"]),
                "unit_price_eur": float(price.price) if price else None,
            }
        )
    return items


def upsert_binder_slot(
    conn,
    *,
    scryfall_id: str,
    finish: str = "nonfoil",
    binder_name: str = "Principal",
    page_number: int = 1,
    slot_number: int = 1,
    condition: str = "near_mint",
    quantity: int = 1,
    notes: str | None = None,
    slot_id: int | None = None,
) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    now = utc_now()
    if slot_id:
        conn.execute(
            """
            UPDATE binder_slots
            SET scryfall_id = ?, finish = ?, binder_name = ?, page_number = ?,
                slot_number = ?, condition = ?, quantity = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                scryfall_id,
                finish,
                binder_name,
                page_number,
                slot_number,
                condition,
                quantity,
                notes,
                now,
                slot_id,
            ),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO binder_slots (
                binder_name, page_number, slot_number, scryfall_id, finish,
                condition, quantity, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binder_name,
                page_number,
                slot_number,
                scryfall_id,
                finish,
                condition,
                quantity,
                notes,
                now,
                now,
            ),
        )
        slot_id = int(cursor.lastrowid)
    conn.commit()
    return {"id": slot_id, "scryfall_id": scryfall_id, "binder_name": binder_name}


def delete_binder_slot(conn, slot_id: int) -> None:
    ensure_collection_app_tables(conn)
    conn.execute("DELETE FROM binder_slots WHERE id = ?", (slot_id,))
    conn.commit()


def export_trade_csv(lines: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "set_code", "scryfall_id", "finish", "quantity", "unit_price_eur", "line_total_eur"])
    for line in lines:
        qty = int(line.get("quantity") or 0)
        unit = float(line.get("unit_price_eur") or 0)
        writer.writerow(
            [
                line.get("name") or "",
                line.get("set_code") or "",
                line.get("scryfall_id") or "",
                line.get("finish") or "nonfoil",
                qty,
                unit,
                round(unit * qty, 2),
            ]
        )
    return buffer.getvalue()


def enrich_trade_lines_with_prices(conn, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for line in lines:
        copy = dict(line)
        if copy.get("unit_price_eur") is None and copy.get("scryfall_id"):
            card = get_cached_card(conn, str(copy["scryfall_id"]))
            if card:
                price = display_price_for(conn, card, str(copy.get("finish") or "nonfoil"))
                if price is not None:
                    copy["unit_price_eur"] = float(price.price)
        enriched.append(copy)
    return enriched


def trade_lines_total_eur(lines: list[dict[str, Any]]) -> float:
    total = 0.0
    for line in lines:
        qty = int(line.get("quantity") or 0)
        unit = float(line.get("unit_price_eur") or 0)
        total += unit * qty
    return round(total, 2)


def export_trade_hw_text(have_lines: list[dict[str, Any]], want_lines: list[dict[str, Any]]) -> str:
    def format_side(lines: list[dict[str, Any]], prefix: str) -> str:
        rows: list[str] = []
        for line in lines:
            qty = max(1, int(line.get("quantity") or 1))
            name = str(line.get("name") or line.get("scryfall_id") or "").strip()
            set_code = str(line.get("set_code") or "").strip().upper()
            if set_code:
                rows.append(f"{qty} {name} ({set_code})")
            else:
                rows.append(f"{qty} {name}")
        return f"{prefix}:\n" + ("\n".join(rows) if rows else "")

    return f"{format_side(have_lines, 'H')}\n\n{format_side(want_lines, 'W')}"


def export_trade_mcm_decklist(lines: list[dict[str, Any]]) -> str:
    from .cardmarket_export import build_wants_decklist_line

    decklist_lines: list[str] = []
    for line in lines:
        qty = max(1, int(line.get("quantity") or 1))
        name = str(line.get("name") or line.get("scryfall_id") or "").strip()
        set_name = str(line.get("set_name") or line.get("set_code") or "").strip()
        decklist_lines.append(build_wants_decklist_line(quantity=qty, name=name, set_name=set_name))
    return "\n".join(decklist_lines)


def parse_trade_decklist_text(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import re

    have_lines: list[dict[str, Any]] = []
    want_lines: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = have_lines
    line_pattern = re.compile(r"^(\d+)x?\s+(.+?)\s+\(([^)]+)\)\s*$", re.IGNORECASE)

    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lowered = stripped.lower().rstrip(":")
        if lowered in {"h", "have"}:
            current = have_lines
            continue
        if lowered in {"w", "want"}:
            current = want_lines
            continue
        match = line_pattern.match(stripped)
        if not match:
            continue
        quantity = max(1, int(match.group(1)))
        name = match.group(2).strip()
        set_code = match.group(3).strip().upper()
        current.append({"quantity": quantity, "name": name, "set_code": set_code})

    if not have_lines and not want_lines:
        current = have_lines
        for raw in (text or "").splitlines():
            match = line_pattern.match(raw.strip())
            if match:
                have_lines.append(
                    {
                        "quantity": max(1, int(match.group(1))),
                        "name": match.group(2).strip(),
                        "set_code": match.group(3).strip().upper(),
                    }
                )
    return have_lines, want_lines


def match_trade_import(conn, text: str) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    cards_table = catalog_table("cards")
    have_parsed, want_parsed = parse_trade_decklist_text(text)
    parsed = want_parsed or have_parsed
    side = "want" if want_parsed else "have"

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    in_collection: list[dict[str, Any]] = []
    not_in_collection: list[dict[str, Any]] = []

    owned_qty: dict[tuple[str, str], int] = {}
    for row in conn.execute(
        "SELECT scryfall_id, finish, SUM(quantity) AS qty FROM collection_items WHERE quantity > 0 GROUP BY scryfall_id, finish"
    ).fetchall():
        owned_qty[(row["scryfall_id"], row["finish"])] = int(row["qty"])

    for entry in parsed:
        name = entry["name"]
        set_code = entry["set_code"]
        quantity = int(entry["quantity"])
        rows = conn.execute(
            f"""
            SELECT scryfall_id, name, set_code, set_name, raw_json
            FROM {cards_table}
            WHERE UPPER(set_code) = ?
              AND (LOWER(name) = LOWER(?) OR LOWER(printed_name) = LOWER(?))
            LIMIT 5
            """,
            (set_code, name, name),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                f"""
                SELECT scryfall_id, name, set_code, set_name, raw_json
                FROM {cards_table}
                WHERE LOWER(name) = LOWER(?) OR LOWER(printed_name) = LOWER(?)
                LIMIT 5
                """,
                (name, name),
            ).fetchall()
        if not rows:
            unmatched.append({**entry, "reason": "carte introuvable"})
            continue
        row = rows[0]
        card = json.loads(row["raw_json"]) if row["raw_json"] else {}
        finish = "nonfoil"
        unit_price = None
        from .database import batch_cardmarket_latest_guide

        guide = batch_cardmarket_latest_guide(conn, [row["scryfall_id"]], finish=finish).get(row["scryfall_id"])
        if guide and guide.get("metrics"):
            trend = guide["metrics"].get("trend")
            if trend is not None:
                unit_price = float(trend)
        item = {
            "scryfall_id": row["scryfall_id"],
            "name": row["name"],
            "set_code": row["set_code"],
            "set_name": row["set_name"],
            "finish": finish,
            "quantity": quantity,
            "unit_price_eur": unit_price,
            "requested_name": name,
            "requested_set_code": set_code,
        }
        matched.append(item)
        owned = owned_qty.get((row["scryfall_id"], finish), 0)
        if owned >= quantity:
            in_collection.append({**item, "owned_quantity": owned})
        else:
            not_in_collection.append({**item, "owned_quantity": owned})

    return {
        "side": side,
        "matched": matched,
        "unmatched": unmatched,
        "in_collection": in_collection,
        "not_in_collection": not_in_collection,
        "parsed_have_count": len(have_parsed),
        "parsed_want_count": len(want_parsed),
    }


def check_price_alerts(conn) -> list[dict[str, Any]]:
    ensure_collection_app_tables(conn)
    rows = conn.execute("SELECT * FROM price_alerts WHERE active = 1").fetchall()
    triggered: list[dict[str, Any]] = []
    now = utc_now()
    for row in rows:
        card = get_cached_card(conn, row["scryfall_id"])
        if not card:
            continue
        price = display_price_for(conn, card, row["finish"])
        if price is None:
            continue
        value = float(price.price)
        threshold = float(row["threshold_eur"])
        direction = str(row["direction"] or "below")
        hit = value <= threshold if direction == "below" else value >= threshold
        if hit:
            card_name = card.get("name")
            conn.execute(
                """
                INSERT INTO price_alert_events (
                    alert_id, scryfall_id, finish, direction, threshold_eur,
                    triggered_eur, triggered_at, name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["scryfall_id"],
                    row["finish"],
                    direction,
                    threshold,
                    value,
                    now,
                    card_name,
                ),
            )
            conn.execute(
                "UPDATE price_alerts SET triggered_at = ?, active = 0 WHERE id = ?",
                (now, row["id"]),
            )
            triggered.append(
                {
                    "id": row["id"],
                    "scryfall_id": row["scryfall_id"],
                    "finish": row["finish"],
                    "threshold_eur": threshold,
                    "current_eur": value,
                    "direction": direction,
                    "name": card_name,
                    "triggered_at": now,
                }
            )
    if triggered:
        conn.commit()
    return triggered


def list_price_alert_events(conn, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_collection_app_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM price_alert_events
        ORDER BY triggered_at DESC, id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 200)),),
    ).fetchall()
    return [dict(row) for row in rows]


def reactivate_price_alert(conn, alert_id: int) -> bool:
    ensure_collection_app_tables(conn)
    cursor = conn.execute(
        "UPDATE price_alerts SET active = 1, triggered_at = NULL WHERE id = ?",
        (alert_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def create_wishlist_price_alert(conn, *, scryfall_id: str, finish: str) -> dict[str, Any] | None:
    ensure_collection_app_tables(conn)
    row = conn.execute(
        "SELECT max_price_eur FROM wishlist_items WHERE scryfall_id = ? AND finish = ?",
        (scryfall_id, finish),
    ).fetchone()
    if row is None or row["max_price_eur"] is None:
        return None
    return create_price_alert(
        conn,
        scryfall_id=scryfall_id,
        finish=finish,
        direction="below",
        threshold_eur=float(row["max_price_eur"]),
    )


def list_binder_names(conn) -> list[str]:
    ensure_collection_app_tables(conn)
    rows = conn.execute(
        "SELECT DISTINCT binder_name FROM binder_slots ORDER BY binder_name"
    ).fetchall()
    names = [row["binder_name"] for row in rows if row["binder_name"]]
    return names or ["Principal"]


def merge_duplicate_collection_rows(conn, scryfall_id: str, finish: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT id, quantity FROM collection_items
        WHERE scryfall_id = ? AND finish = ? AND quantity > 0
        ORDER BY id
        """,
        (scryfall_id, finish),
    ).fetchall()
    if len(rows) <= 1:
        return {"merged": 0, "total_qty": int(rows[0]["quantity"]) if rows else 0}
    keep_id = rows[0]["id"]
    total_qty = sum(int(row["quantity"]) for row in rows)
    conn.execute("UPDATE collection_items SET quantity = ?, updated_at = ? WHERE id = ?", (total_qty, utc_now(), keep_id))
    conn.execute(
        "DELETE FROM collection_items WHERE scryfall_id = ? AND finish = ? AND id != ?",
        (scryfall_id, finish, keep_id),
    )
    conn.commit()
    return {"merged": len(rows) - 1, "total_qty": total_qty}


def deck_cards_to_buy(conn, deck_cards: list[dict[str, Any]]) -> dict[str, Any]:
    from .database import owned_counts_by_card_finish

    owned = owned_counts_by_card_finish(conn)
    lines: list[dict[str, Any]] = []
    total = Decimal("0")
    for deck_card in deck_cards:
        key = (deck_card["scryfall_id"], deck_card["finish"])
        owned_qty = int(owned.get(key, 0))
        need = int(deck_card["quantity"]) - owned_qty
        if need <= 0:
            continue
        card = get_cached_card(conn, deck_card["scryfall_id"])
        price = display_price_for(conn, card, deck_card["finish"]) if card else None
        unit = float(price.price) if price else None
        line_total = Decimal(str(unit * need)) if unit is not None else None
        if line_total is not None:
            total += line_total
        lines.append(
            {
                "scryfall_id": deck_card["scryfall_id"],
                "name": deck_card.get("name") or (card.get("name") if card else deck_card["scryfall_id"]),
                "finish": deck_card["finish"],
                "quantity": need,
                "set_code": deck_card.get("set_code"),
                "collector_number": deck_card.get("collector_number"),
                "unit_price_eur": unit,
                "line_total_eur": float(line_total) if line_total is not None else None,
                "image_url": catalog_image_url(deck_card["scryfall_id"]),
            }
        )
    return {
        "lines": lines,
        "line_count": len(lines),
        "total_cards": sum(line["quantity"] for line in lines),
        "total_eur": decimal_to_json(total),
    }


def export_app_backup(conn) -> dict[str, Any]:
    ensure_collection_app_tables(conn)
    cards_table = catalog_table("cards")
    collection_rows = conn.execute(
        f"""
        SELECT ci.*, c.name, c.set_code
        FROM collection_items ci
        LEFT JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
        """
    ).fetchall()
    return {
        "exported_at": utc_now(),
        "collection": [dict(row) for row in collection_rows],
        "wishlist": list_wishlist(conn),
        "price_alerts": list_price_alerts(conn),
        "price_alert_events": list_price_alert_events(conn, limit=200),
        "binder": [dict(row) for row in conn.execute(
            "SELECT * FROM binder_slots ORDER BY binder_name, page_number, slot_number"
        ).fetchall()],
    }
