from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from .database import connect, decimal_to_json, init_db
from .local_cache import (
    CacheError,
    catalog_image_url,
    cached_set_codes,
    load_set_list,
    load_set_json,
    load_set_stats_cache,
    save_set_stats_cache,
    set_json_path,
)
from .mtgjson import set_name_map


INNISTRAD_CUTOFF = "2011-09-30"

CATEGORY_ORDER = [
    "extensions_principales",
    "anciennes_extensions",
    "produits_speciaux",
    "decks",
    "promos_evenements",
]

CATEGORY_LABELS = {
    "extensions_principales": "Extensions principales",
    "anciennes_extensions": "Anciennes extensions",
    "produits_speciaux": "Produits speciaux",
    "decks": "Decks",
    "promos_evenements": "Promos et evenements",
}

SPECIAL_TYPES = {
    "masters",
    "from_the_vault",
    "funny",
    "spellbook",
    "masterpiece",
    "memorabilia",
    "alchemy",
    "draft_innovation",
    "treasure_chest",
    "vanguard",
}

DECK_TYPES = {
    "duel_deck",
    "box",
    "premium_deck",
    "archenemy",
    "planechase",
    "arsenal",
    "starter",
    "commander",
}

PROMO_TYPES = {"promo", "minigame"}

MAIN_EXTENSION_TYPES = {"expansion", "core"}

SECTION_LABELS = {
    "expansion": "Extension principale",
    "core": "Extension principale",
    "commander": "Commander Decks",
    "promo": "Promos",
    "memorabilia": "Art Series",
    "alchemy": "Alchemy",
    "token": "Tokens",
    "draft_innovation": "Innovation",
}


def top_level_sets() -> list[dict[str, Any]]:
    return [entry for entry in load_set_list() if not entry.get("parentCode")]


def categorize_set(entry: dict[str, Any]) -> str | None:
    set_type = entry.get("type") or ""
    release_date = entry.get("releaseDate") or ""

    if set_type in MAIN_EXTENSION_TYPES:
        if release_date >= INNISTRAD_CUTOFF:
            return "extensions_principales"
        return "anciennes_extensions"
    if set_type in SPECIAL_TYPES:
        return "produits_speciaux"
    if set_type in DECK_TYPES:
        return "decks"
    if set_type in PROMO_TYPES:
        return "promos_evenements"
    if set_type == "token":
        return "produits_speciaux"
    return None


def set_tile(entry: dict[str, Any]) -> dict[str, Any]:
    code = (entry.get("code") or "").upper()
    return {
        "code": code,
        "name": entry.get("name") or code,
        "release_date": entry.get("releaseDate"),
        "type": entry.get("type"),
        "total_cards": int(entry.get("totalSetSize") or entry.get("baseSetSize") or 0),
        "token_set_code": entry.get("tokenSetCode"),
    }


def blocks_catalog() -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_ORDER}
    for entry in top_level_sets():
        category = categorize_set(entry)
        if category is None:
            continue
        grouped[category].append(set_tile(entry))

    for category in grouped:
        if category == "extensions_principales" or category == "anciennes_extensions":
            grouped[category].sort(key=lambda item: item.get("release_date") or "", reverse=True)
        elif category == "produits_speciaux" or category == "decks":
            grouped[category].sort(key=lambda item: (item.get("name") or "").lower())
        else:
            grouped[category].sort(key=lambda item: item.get("release_date") or "", reverse=True)

    return [
        {
            "id": category,
            "label": CATEGORY_LABELS[category],
            "count": len(grouped[category]),
            "sets": grouped[category],
        }
        for category in CATEGORY_ORDER
        if grouped[category]
    ]


def child_sets(parent_code: str) -> list[dict[str, Any]]:
    parent = parent_code.upper()
    children = [
        set_tile(entry)
        for entry in load_set_list()
        if (entry.get("parentCode") or "").upper() == parent
    ]
    return sorted(children, key=lambda item: (item.get("name") or "").lower())


def section_label(entry: dict[str, Any]) -> str:
    set_type = entry.get("type") or ""
    return SECTION_LABELS.get(set_type, entry.get("name") or entry.get("code") or "Section")


def set_sections(set_code: str) -> dict[str, Any]:
    code = set_code.upper()
    entries = [entry for entry in load_set_list() if (entry.get("code") or "").upper() == code]
    if not entries:
        raise ValueError(f"Extension inconnue: {code}")
    entry = entries[0]
    sections: list[dict[str, Any]] = [
        {
            "code": code,
            "label": section_label(set_tile(entry)),
            "type": entry.get("type"),
        }
    ]
    token_code = entry.get("tokenSetCode")
    if token_code:
        sections.append(
            {
                "code": token_code.upper(),
                "label": "Tokens",
                "type": "token",
            }
        )
    for child in child_sets(code):
        sections.append(
            {
                "code": child["code"],
                "label": section_label(child),
                "type": child.get("type"),
            }
        )
    return {
        "set": set_tile(entry),
        "sections": sections,
    }


def owned_counts_by_scryfall(conn) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT scryfall_id, SUM(quantity) AS quantity
        FROM collection_items
        GROUP BY scryfall_id
        """
    ).fetchall()
    return {row["scryfall_id"]: int(row["quantity"]) for row in rows}


def collector_sort_key(number: str | None) -> tuple:
    if not number:
        return (999999, "")
    parts = re.split(r"(\d+)", str(number))
    key: list[Any] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        elif part:
            key.append(part.lower())
    return tuple(key)


def card_sort_value(card: dict[str, Any], sort_key: str) -> Any:
    if sort_key == "price":
        return card.get("price_nonfoil") or card.get("price_foil") or 0
    if sort_key == "name":
        return (card.get("name") or "").lower()
    if sort_key == "number":
        return collector_sort_key(card.get("number"))
    return 0


def parse_sort_spec(sort: str) -> list[tuple[str, bool]]:
    specs: list[tuple[str, bool]] = []
    for token in (part.strip() for part in sort.split(",") if part.strip()):
        if token.endswith("_desc"):
            specs.append((token[: -len("_desc")], True))
        elif token.endswith("_asc"):
            specs.append((token[: -len("_asc")], False))
        elif token in {"price", "name", "number"}:
            specs.append((token, False))
    if not specs:
        specs.append(("price", True))
    return specs


def sort_cards(cards: list[dict[str, Any]], sort: str) -> None:
    for field, reverse in reversed(parse_sort_spec(sort)):
        if field not in {"price", "name", "number"}:
            continue
        cards.sort(key=lambda card: card_sort_value(card, field), reverse=reverse)


def scryfall_ids_for_set_code(set_code: str) -> list[str]:
    try:
        payload = load_set_json(set_code.upper())
    except CacheError:
        return []
    ids = {
        (card.get("identifiers") or {}).get("scryfallId")
        for card in payload.get("cards") or []
        if (card.get("identifiers") or {}).get("scryfallId")
    }
    return sorted(ids)


def scryfall_ids_for_set_block(set_code: str) -> list[str]:
    ids: set[str] = set()
    for section in set_sections(set_code)["sections"]:
        ids.update(scryfall_ids_for_set_code(section["code"]))
    return sorted(ids)


def price_from_scryfall_card(scryfall_card: dict[str, Any], finish: str) -> float | None:
    prices = scryfall_card.get("prices") or {}
    key = {"nonfoil": "eur", "foil": "eur_foil", "etched": "eur_etched"}.get(finish, "eur")
    value = prices.get(key)
    if value in (None, ""):
        return None
    return float(value)


def card_prices_eur(card: dict[str, Any]) -> dict[str, float | None]:
    prices = card.get("prices") or {}
    nonfoil = prices.get("eur")
    foil = prices.get("eur_foil")
    return {
        "nonfoil": float(nonfoil) if nonfoil not in (None, "") else None,
        "foil": float(foil) if foil not in (None, "") else None,
    }


def compute_set_stats_fast(set_code: str, owned: dict[str, int]) -> dict[str, Any] | None:
    path = set_json_path(set_code)
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    cards = [card for card in payload.get("cards") or [] if not card.get("isFunny")]
    owned_cards = 0
    owned_value = Decimal("0")
    total_value = Decimal("0")

    for card in cards:
        identifiers = card.get("identifiers") or {}
        scryfall_id = identifiers.get("scryfallId")
        quantity = owned.get(scryfall_id, 0) if scryfall_id else 0
        prices = card_prices_eur(card)
        price = prices["nonfoil"] or prices["foil"]
        if price is not None:
            total_value += Decimal(str(price))
            if quantity:
                owned_cards += quantity
                owned_value += Decimal(str(price)) * quantity

    return {
        "total_cards": len(cards) or int(payload.get("totalSetSize") or payload.get("baseSetSize") or 0),
        "owned_cards": owned_cards,
        "owned_value_eur": float(owned_value),
        "total_value_eur": float(total_value),
    }


def refresh_set_stats_cache(set_code: str) -> dict[str, Any] | None:
    stats = compute_set_stats_fast(set_code, {})
    if stats is None:
        return None

    code = set_code.upper()
    cache = load_set_stats_cache()
    cache[code] = {
        "total_cards": stats["total_cards"],
        "total_value_eur": stats["total_value_eur"],
    }
    save_set_stats_cache(cache)
    return cache[code]


def summarize_set_values(set_code: str, owned: dict[str, int], conn=None) -> tuple[int, float, float]:
    stats = compute_set_stats_fast(set_code, owned)
    if stats is None:
        return 0, 0.0, 0.0
    return stats["owned_cards"], stats["owned_value_eur"], stats["total_value_eur"]


def mtgjson_card_to_payload(
    card: dict[str, Any],
    owned: dict[str, int],
    scryfall_cards: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identifiers = card.get("identifiers") or {}
    scryfall_id = identifiers.get("scryfallId")
    finishes = card.get("finishes") or ["nonfoil"]
    finish = "foil" if "foil" in finishes and "nonfoil" not in finishes else "nonfoil"
    quantity = owned.get(scryfall_id, 0) if scryfall_id else 0
    prices = card_prices_eur(card)

    if scryfall_id and scryfall_cards and scryfall_id in scryfall_cards:
        scryfall_card = scryfall_cards[scryfall_id]
        live_nonfoil = price_from_scryfall_card(scryfall_card, "nonfoil")
        live_foil = price_from_scryfall_card(scryfall_card, "foil")
        if live_nonfoil is not None:
            prices["nonfoil"] = live_nonfoil
        if live_foil is not None:
            prices["foil"] = live_foil

    return {
        "uuid": card.get("uuid"),
        "scryfall_id": scryfall_id,
        "name": card.get("name"),
        "number": card.get("number"),
        "rarity": card.get("rarity"),
        "finish": finish,
        "quantity": quantity,
        "owned": quantity > 0,
        "image_url": catalog_image_url(scryfall_id),
        "price_nonfoil": prices["nonfoil"],
        "price_foil": prices["foil"],
    }


def set_cards(set_code: str, *, sort: str = "price_desc") -> dict[str, Any]:
    code = set_code.upper()
    try:
        payload = load_set_json(code)
    except CacheError as error:
        entry = set_list_entry(code)
        names = set_name_map()
        conn = connect()
        init_db(conn)
        owned_count = owned_cards_for_set_code(conn, code)
        conn.close()
        return {
            "set_code": code,
            "set_name": (entry or {}).get("name") or names.get(code) or code,
            "summary": {
                "owned_cards": owned_count,
                "owned_unique": 0,
                "total_cards": int((entry or {}).get("totalSetSize") or (entry or {}).get("baseSetSize") or 0),
                "owned_value_eur": 0,
                "total_value_eur": 0,
            },
            "cards": [],
            "unavailable": True,
            "error": str(error),
        }

    cards = payload.get("cards") or []

    conn = connect()
    init_db(conn)
    owned = owned_counts_by_scryfall(conn)

    scryfall_ids = sorted(
        {
            (card.get("identifiers") or {}).get("scryfallId")
            for card in cards
            if (card.get("identifiers") or {}).get("scryfallId")
        }
    )
    scryfall_cards: dict[str, dict[str, Any]] = {}
    if scryfall_ids:
        placeholders = ",".join("?" for _ in scryfall_ids)
        rows = conn.execute(
            f"SELECT scryfall_id, raw_json FROM cards WHERE scryfall_id IN ({placeholders})",
            scryfall_ids,
        ).fetchall()
        scryfall_cards = {row["scryfall_id"]: json.loads(row["raw_json"]) for row in rows}

    rendered = [
        mtgjson_card_to_payload(card, owned, scryfall_cards)
        for card in cards
        if not card.get("isFunny", False)
    ]

    sort_cards(rendered, sort)

    owned_cards = sum(card["quantity"] for card in rendered)
    owned_unique = sum(1 for card in rendered if card["owned"])
    total_cards = len(rendered)
    owned_value = Decimal("0")
    total_value = Decimal("0")
    for card in rendered:
        price = card.get("price_nonfoil") or card.get("price_foil")
        if price is not None:
            total_value += Decimal(str(price))
            if card["quantity"]:
                owned_value += Decimal(str(price)) * card["quantity"]

    conn.close()
    names = set_name_map()
    refresh_set_stats_cache(code)
    return {
        "set_code": code,
        "set_name": payload.get("name") or names.get(code) or code,
        "summary": {
            "owned_cards": owned_cards,
            "owned_unique": owned_unique,
            "total_cards": total_cards,
            "owned_value_eur": decimal_to_json(owned_value),
            "total_value_eur": decimal_to_json(total_value),
        },
        "cards": rendered,
    }


def enrich_blocks_with_collection(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conn = connect()
    init_db(conn)

    rows = conn.execute(
        """
        SELECT c.set_code, SUM(ci.quantity) AS owned_cards
        FROM collection_items ci
        JOIN cards c ON c.scryfall_id = ci.scryfall_id
        WHERE c.set_code IS NOT NULL
        GROUP BY c.set_code
        """
    ).fetchall()
    owned_by_set = {(row["set_code"] or "").upper(): int(row["owned_cards"]) for row in rows}

    cached_codes = cached_set_codes()
    stats_cache = load_set_stats_cache()
    owned = owned_counts_by_scryfall(conn) if owned_by_set else {}

    enriched: list[dict[str, Any]] = []
    for category in categories:
        sets = []
        for entry in category["sets"]:
            code = entry["code"]
            owned_cards = owned_by_set.get(code, 0)
            total_value_eur = None
            owned_value_eur = None

            cached_stats = stats_cache.get(code)
            if cached_stats:
                total_value_eur = cached_stats.get("total_value_eur")

            if code in cached_codes:
                if cached_stats is None:
                    cached_stats = refresh_set_stats_cache(code)
                    if cached_stats:
                        total_value_eur = cached_stats.get("total_value_eur")
                if owned_cards > 0:
                    fast_stats = compute_set_stats_fast(code, owned)
                    if fast_stats:
                        owned_cards = max(owned_cards, fast_stats["owned_cards"])
                        owned_value_eur = fast_stats["owned_value_eur"]

            sets.append(
                {
                    **entry,
                    "owned_cards": owned_cards,
                    "owned_value_eur": owned_value_eur,
                    "total_value_eur": total_value_eur,
                }
            )
        enriched.append({**category, "sets": sets})
    conn.close()
    return enriched


def set_list_entry(set_code: str) -> dict[str, Any] | None:
    code = set_code.upper()
    for entry in load_set_list():
        if (entry.get("code") or "").upper() == code:
            return entry
    return None


def owned_cards_for_set_code(conn, set_code: str) -> int:
    row = conn.execute(
        """
        SELECT SUM(ci.quantity) AS quantity
        FROM collection_items ci
        JOIN cards c ON c.scryfall_id = ci.scryfall_id
        WHERE UPPER(c.set_code) = ?
        """,
        (set_code.upper(),),
    ).fetchone()
    return int(row["quantity"] or 0) if row else 0


def section_summary(section_code: str, owned: dict[str, int], conn) -> dict[str, Any]:
    code = section_code.upper()
    fast_stats = compute_set_stats_fast(code, owned)
    if fast_stats:
        return {
            "total_cards": fast_stats["total_cards"],
            "owned_cards": fast_stats["owned_cards"],
            "owned_value_eur": fast_stats["owned_value_eur"],
            "total_value_eur": fast_stats["total_value_eur"] or None,
        }

    entry = set_list_entry(code)
    total_cards = int(entry.get("totalSetSize") or entry.get("baseSetSize") or 0) if entry else 0
    return {
        "total_cards": total_cards,
        "owned_cards": owned_cards_for_set_code(conn, code),
        "owned_value_eur": 0.0,
        "total_value_eur": None,
    }


def enrich_sections_with_stats(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conn = connect()
    init_db(conn)
    owned = owned_counts_by_scryfall(conn)
    enriched = []
    for section in sections:
        enriched.append({**section, **section_summary(section["code"], owned, conn)})
    conn.close()
    return enriched
