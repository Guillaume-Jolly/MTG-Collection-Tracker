from __future__ import annotations

import json
import re
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .database import (
    build_language_siblings_for_collectors,
    build_set_language_siblings,
    batch_latest_snapshots,
    catalog_table,
    connect,
    decimal_to_json,
    display_price_for,
    display_price_source_label,
    finish_breakdown_for_scryfall,
    get_cached_card,
    init_db,
    language_sibling_ids_db,
    owned_counts_by_card_finish,
    resolve_display_card_db,
    resolve_display_card_id,
)
from .prices import current_eur_price
from .local_cache import (
    CacheError,
    catalog_image_url,
    cached_set_codes,
    local_set_icon_url,
    load_set_list,
    load_set_json,
    load_set_stats_cache,
    merge_set_stats_cache_entries,
    upsert_set_stats_cache_entry,
    set_json_path,
)
from .mtgjson import set_name_map


INNISTRAD_CUTOFF = "2011-09-30"
# Strixhaven: School of Mages — market scope starts here (modern sets, not full catalogue).
MARKET_MIN_RELEASE_DATE = "2021-04-23"

_MARKET_ELIGIBLE_SET_CODES: frozenset[str] | None = None


def market_eligible_set_codes(*, refresh: bool = False) -> frozenset[str]:
    global _MARKET_ELIGIBLE_SET_CODES
    if _MARKET_ELIGIBLE_SET_CODES is not None and not refresh:
        return _MARKET_ELIGIBLE_SET_CODES
    codes: set[str] = set()
    for entry in load_set_list():
        release = str(entry.get("releaseDate") or "")
        if release >= MARKET_MIN_RELEASE_DATE:
            code = str(entry.get("code") or "").upper()
            if code:
                codes.add(code)
    _MARKET_ELIGIBLE_SET_CODES = frozenset(codes)
    return _MARKET_ELIGIBLE_SET_CODES


_SET_RELEASE_BY_CODE: dict[str, str] | None = None


def set_release_date_by_code(*, refresh: bool = False) -> dict[str, str]:
    global _SET_RELEASE_BY_CODE
    if _SET_RELEASE_BY_CODE is not None and not refresh:
        return _SET_RELEASE_BY_CODE
    mapping: dict[str, str] = {}
    for entry in load_set_list():
        code = str(entry.get("code") or "").upper()
        release = str(entry.get("releaseDate") or "")
        if code and release:
            mapping[code] = release
    _SET_RELEASE_BY_CODE = mapping
    return _SET_RELEASE_BY_CODE


def set_age_years(set_code: str, *, as_of: date) -> float | None:
    release = set_release_date_by_code().get(set_code.upper())
    if not release:
        return None
    try:
        release_date = date.fromisoformat(release)
    except ValueError:
        return None
    days = (as_of - release_date).days
    if days < 0:
        return None
    return days / 365.25


GROUP_ORDER = [
    "secret_lair",
    "universes_beyond",
]

GROUP_LABELS = {
    "secret_lair": "Secret Lair",
    "universes_beyond": "Universes Beyond",
}

COLLECTION_CATALOG_VERSION = 2

SECRET_LAIR_CODES = frozenset({"SLD", "SLU", "SLC", "SLP", "SLX", "PSSC"})

UNIVERSES_BEYOND_ROOT_CODES = frozenset(
    {
        "40K",
        "ACR",
        "FIN",
        "HBG",
        "HOB",
        "LTR",
        "MAR",
        "MSH",
        "PIP",
        "SPM",
        "TLA",
        "TMT",
        "TRK",
        "UNF",
        "WHO",
    }
)

UNIVERSES_BEYOND_EXTRA_CODES = frozenset(
    {
        "BOT",
        "CLU",
        "FIC",
        "LTC",
        "MSC",
        "OM1",
        "REX",
        "SPE",
        "TLE",
        "TMC",
        "TRC",
    }
)

UNIVERSES_BEYOND_NAME_MARKERS = (
    "assassin's creed",
    "avatar:",
    "avatar ",
    "doctor who",
    "fallout",
    "final fantasy",
    "fortnite",
    "god of war",
    "hatsune miku",
    "jurassic",
    "lord of the rings",
    "marvel",
    "middle-earth",
    "spider-man",
    "star trek",
    "stranger things",
    "tales of middle-earth",
    "teenage mutant ninja",
    "the hobbit",
    "the last of us",
    "the walking dead",
    "transformers",
    "unfinity",
    "warhammer",
)

UNIVERSES_BEYOND_HOIST_TYPES = frozenset(
    {
        "alchemy",
        "box",
        "commander",
        "core",
        "draft_innovation",
        "eternal",
        "expansion",
        "funny",
    }
)

BLOCK_CATEGORY_ORDER = [
    *GROUP_ORDER,
    "extensions_principales",
    "anciennes_extensions",
    "produits_speciaux",
    "decks",
    "promos_evenements",
]

CATEGORY_ORDER = BLOCK_CATEGORY_ORDER[len(GROUP_ORDER) :]

BLOCK_CATEGORY_LABELS = {
    **GROUP_LABELS,
    "extensions_principales": "Extensions principales",
    "anciennes_extensions": "Anciennes extensions",
    "produits_speciaux": "Produits speciaux",
    "decks": "Decks",
    "promos_evenements": "Promos et evenements",
}

CATEGORY_LABELS = {
    key: BLOCK_CATEGORY_LABELS[key]
    for key in CATEGORY_ORDER
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


def is_secret_lair_set(entry: dict[str, Any]) -> bool:
    code = (entry.get("code") or "").upper()
    parent = (entry.get("parentCode") or "").upper()
    name = (entry.get("name") or "").lower()
    if parent == "SLD":
        return True
    if code in SECRET_LAIR_CODES:
        return True
    return "secret lair" in name


def is_universes_beyond_set(entry: dict[str, Any]) -> bool:
    code = (entry.get("code") or "").upper()
    parent = (entry.get("parentCode") or "").upper()
    set_type = entry.get("type") or ""
    name = (entry.get("name") or "").lower()
    if code in UNIVERSES_BEYOND_ROOT_CODES or code in UNIVERSES_BEYOND_EXTRA_CODES:
        return True
    if parent in UNIVERSES_BEYOND_ROOT_CODES:
        return set_type in UNIVERSES_BEYOND_HOIST_TYPES
    if not parent and set_type in {"commander", "core", "draft_innovation", "expansion"}:
        return any(marker in name for marker in UNIVERSES_BEYOND_NAME_MARKERS)
    return False


def collection_group_for(entry: dict[str, Any]) -> str | None:
    if is_secret_lair_set(entry):
        return "secret_lair"
    if is_universes_beyond_set(entry):
        return "universes_beyond"
    return None


def sort_category_sets(category: str, sets: list[dict[str, Any]]) -> None:
    if category in {"secret_lair", "universes_beyond", "extensions_principales", "anciennes_extensions", "promos_evenements"}:
        sets.sort(key=lambda item: item.get("release_date") or "", reverse=True)
    elif category in {"produits_speciaux", "decks"}:
        sets.sort(key=lambda item: (item.get("name") or "").lower())
    else:
        sets.sort(key=lambda item: item.get("release_date") or "", reverse=True)


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


def set_icon_slug(entry: dict[str, Any]) -> str:
    code = (entry.get("code") or "").upper()
    keyrune = (entry.get("keyruneCode") or "").strip()
    if keyrune and keyrune.upper() != "DEFAULT":
        return keyrune.lower()
    return code.lower()


def set_icon_meta(entry: dict[str, Any] | None, *, code: str = "") -> dict[str, str]:
    item = entry or {}
    set_code = (item.get("code") or code or "").upper()
    slug = set_icon_slug(item) if item else (code or "").lower()
    keyrune = (item.get("keyruneCode") or set_code or code).upper()
    return {
        "keyrune_code": keyrune,
        "icon_slug": slug,
        "icon_url": local_set_icon_url(slug),
    }


def set_tile(entry: dict[str, Any]) -> dict[str, Any]:
    code = (entry.get("code") or "").upper()
    return {
        "code": code,
        "name": entry.get("name") or code,
        "release_date": entry.get("releaseDate"),
        "type": entry.get("type"),
        "total_cards": int(entry.get("totalSetSize") or entry.get("baseSetSize") or 0),
        "token_set_code": entry.get("tokenSetCode"),
        **set_icon_meta(entry),
    }


def blocks_catalog() -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in BLOCK_CATEGORY_ORDER}
    assigned_codes: set[str] = set()

    for entry in load_set_list():
        group = collection_group_for(entry)
        if group is None:
            continue
        tile = set_tile(entry)
        if tile["code"] in assigned_codes:
            continue
        assigned_codes.add(tile["code"])
        grouped[group].append(tile)

    for entry in top_level_sets():
        code = (entry.get("code") or "").upper()
        if code in assigned_codes:
            continue
        category = categorize_set(entry)
        if category is None:
            continue
        assigned_codes.add(code)
        grouped[category].append(set_tile(entry))

    for category in grouped:
        sort_category_sets(category, grouped[category])

    return [
        {
            "id": category,
            "label": BLOCK_CATEGORY_LABELS[category],
            "count": len(grouped[category]),
            "group": "franchise" if category in GROUP_ORDER else "default",
            "sets": grouped[category],
        }
        for category in BLOCK_CATEGORY_ORDER
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


def section_with_icon(section: dict[str, Any]) -> dict[str, Any]:
    entry = set_list_entry(section["code"])
    return {**section, **set_icon_meta(entry, code=section["code"])}


def set_sections(set_code: str) -> dict[str, Any]:
    code = set_code.upper()
    entries = [entry for entry in load_set_list() if (entry.get("code") or "").upper() == code]
    if not entries:
        raise ValueError(f"Extension inconnue: {code}")
    entry = entries[0]
    sections: list[dict[str, Any]] = [
        section_with_icon(
            {
                "code": code,
                "label": section_label(set_tile(entry)),
                "type": entry.get("type"),
            }
        )
    ]
    token_code = entry.get("tokenSetCode")
    if token_code:
        sections.append(
            section_with_icon(
                {
                    "code": token_code.upper(),
                    "label": "Tokens",
                    "type": "token",
                }
            )
        )
    for child in child_sets(code):
        sections.append(
            section_with_icon(
                {
                    "code": child["code"],
                    "label": section_label(child),
                    "type": child.get("type"),
                }
            )
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


RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3, "special": 4, "bonus": 5}
COLOR_ORDER = {"W": 0, "U": 1, "B": 2, "R": 3, "G": 4}
SORT_FIELDS = {
    "price",
    "name",
    "number",
    "cmc",
    "type",
    "subtype",
    "color",
    "set",
    "rarity",
    "finish",
    "quantity",
    "owned",
}


def card_type_parts(type_line: str | None) -> tuple[str, str]:
    if not type_line:
        return "", ""
    parts = re.split(r"\s*[—–]\s*", type_line, maxsplit=1)
    if len(parts) == 1:
        return parts[0].strip().lower(), ""
    return parts[0].strip().lower(), parts[1].strip().lower()


def color_sort_key(colors: list[str] | None) -> str:
    if not colors:
        return "Z"
    return "".join(sorted(colors, key=lambda color: COLOR_ORDER.get(color, 9)))


def card_sort_value(card: dict[str, Any], sort_key: str) -> Any:
    if sort_key == "price":
        unit_price = card.get("unit_price_eur")
        if unit_price is not None:
            return unit_price
        finish = card.get("finish") or "nonfoil"
        if finish == "foil":
            return card.get("price_foil") or card.get("price_nonfoil") or 0
        return card.get("price_nonfoil") or card.get("price_foil") or 0
    if sort_key == "name":
        return (card.get("name") or "").lower()
    if sort_key == "number":
        return collector_sort_key(card.get("number"))
    if sort_key == "cmc":
        return card.get("cmc") or 0
    if sort_key == "type":
        return card.get("card_type") or card_type_parts(card.get("type_line"))[0]
    if sort_key == "subtype":
        return card.get("subtype") or card_type_parts(card.get("type_line"))[1]
    if sort_key == "color":
        return color_sort_key(card.get("colors"))
    if sort_key == "set":
        return (card.get("set_name") or card.get("set_code") or "").lower()
    if sort_key == "rarity":
        return RARITY_ORDER.get((card.get("rarity") or "").lower(), -1)
    if sort_key == "finish":
        return (card.get("finish") or "").lower()
    if sort_key == "quantity":
        return card.get("quantity") or 0
    if sort_key == "owned":
        return 1 if card.get("owned") or (card.get("quantity") or 0) > 0 else 0
    return 0


def parse_sort_spec(sort: str) -> list[tuple[str, bool]]:
    specs: list[tuple[str, bool]] = []
    for token in (part.strip() for part in sort.split(",") if part.strip()):
        if token.endswith("_desc"):
            specs.append((token[: -len("_desc")], True))
        elif token.endswith("_asc"):
            specs.append((token[: -len("_asc")], False))
        elif token in SORT_FIELDS:
            specs.append((token, False))
    if not specs:
        specs.append(("price", True))
    return specs


def sort_cards(cards: list[dict[str, Any]], sort: str) -> None:
    for field, reverse in reversed(parse_sort_spec(sort)):
        if field not in SORT_FIELDS:
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

    try:
        payload = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    except json.JSONDecodeError:
        return None
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
    return upsert_set_stats_cache_entry(
        code,
        {
            "total_cards": stats["total_cards"],
            "total_value_eur": stats["total_value_eur"],
        },
    )


def summarize_set_values(set_code: str, owned: dict[str, int], conn=None) -> tuple[int, float, float]:
    stats = compute_set_stats_fast(set_code, owned)
    if stats is None:
        return 0, 0.0, 0.0
    return stats["owned_cards"], stats["owned_value_eur"], stats["total_value_eur"]


def mtgjson_card_to_payload(
    card: dict[str, Any],
    owned: dict[str, int],
    scryfall_cards: dict[str, dict[str, Any]] | None = None,
    set_siblings: dict[str, dict[str, str]] | None = None,
    display_lang: str = "merge",
    *,
    owned_by_finish: dict[tuple[str, str], int] | None = None,
) -> dict[str, Any]:
    identifiers = card.get("identifiers") or {}
    scryfall_id = identifiers.get("scryfallId")
    finishes = card.get("finishes") or ["nonfoil"]
    default_finish = "foil" if "foil" in finishes and "nonfoil" not in finishes else "nonfoil"
    if owned_by_finish is not None:
        finish_breakdown = finish_breakdown_for_scryfall(owned_by_finish, scryfall_id)
        quantity = sum(finish_breakdown.values())
        finish = next(
            (entry for entry in ("nonfoil", "foil", "etched") if finish_breakdown.get(entry)),
            default_finish,
        )
    else:
        finish_breakdown = {}
        quantity = owned.get(scryfall_id, 0) if scryfall_id else 0
        finish = default_finish
        if quantity > 0:
            finish_breakdown = {finish: quantity}
    prices = card_prices_eur(card)
    display_scryfall_id = scryfall_id
    display_name = card.get("name")

    if scryfall_id and scryfall_cards and scryfall_id in scryfall_cards:
        base_card = scryfall_cards[scryfall_id]
        collector_number = str(base_card.get("collector_number") or card.get("number") or "").strip()
        siblings = set_siblings.get(collector_number, {}) if set_siblings else {}
        current_lang = str(base_card.get("lang") or "en").lower()
        siblings = {**siblings, current_lang: scryfall_id}
        display_scryfall_id = resolve_display_card_id(base_card, siblings, display_lang)
        display_card = scryfall_cards.get(display_scryfall_id, base_card)
        display_name = display_card.get("printed_name") or display_card.get("name") or display_name
        live_nonfoil = price_from_scryfall_card(display_card, "nonfoil")
        live_foil = price_from_scryfall_card(display_card, "foil")
        if live_nonfoil is not None:
            prices["nonfoil"] = live_nonfoil
        if live_foil is not None:
            prices["foil"] = live_foil

    return {
        "uuid": card.get("uuid"),
        "scryfall_id": scryfall_id,
        "name": display_name,
        "number": card.get("number"),
        "rarity": card.get("rarity"),
        "finish": finish,
        "quantity": quantity,
        "finish_breakdown": finish_breakdown,
        "owned": quantity > 0,
        "image_url": catalog_image_url(display_scryfall_id),
        "price_nonfoil": prices["nonfoil"],
        "price_foil": prices["foil"],
    }


def set_cards(set_code: str, *, sort: str = "price_desc", display_lang: str = "merge") -> dict[str, Any]:
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
    owned_by_finish = owned_counts_by_card_finish(conn)

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
        cards_table = catalog_table("cards")
        rows = conn.execute(
            f"SELECT scryfall_id, raw_json FROM {cards_table} WHERE scryfall_id IN ({placeholders})",
            scryfall_ids,
        ).fetchall()
        scryfall_cards = {row["scryfall_id"]: json.loads(row["raw_json"]) for row in rows}

    set_siblings = build_set_language_siblings(conn, code) if display_lang == "merge" else {}
    sibling_row_cache: dict[tuple[str, str], dict[str, str]] = {}
    if display_lang != "merge":
        needed_numbers: set[str] = set()
        for card in cards:
            if card.get("isFunny", False):
                continue
            scryfall_id = (card.get("identifiers") or {}).get("scryfallId")
            if not scryfall_id or scryfall_id not in scryfall_cards:
                continue
            base_card = scryfall_cards[scryfall_id]
            collector_number = str(base_card.get("collector_number") or card.get("number") or "").strip()
            card_lang = str(base_card.get("lang") or "en").lower()
            if card_lang != display_lang and collector_number:
                needed_numbers.add(collector_number)
        if needed_numbers:
            sibling_row_cache = build_language_siblings_for_collectors(conn, {code.lower(): needed_numbers})
    rendered = []
    for card in cards:
        if card.get("isFunny", False):
            continue
        scryfall_id = (card.get("identifiers") or {}).get("scryfallId")
        row_siblings = set_siblings
        if display_lang != "merge" and scryfall_id and scryfall_id in scryfall_cards:
            base_card = scryfall_cards[scryfall_id]
            collector_number = str(base_card.get("collector_number") or card.get("number") or "").strip()
            card_lang = str(base_card.get("lang") or "en").lower()
            if card_lang != display_lang and collector_number:
                resolved = sibling_row_cache.get((code.lower(), collector_number), {})
                if resolved:
                    resolved = {**resolved, card_lang: scryfall_id}
                else:
                    resolved = language_sibling_ids_db(conn, base_card)
                row_siblings = {collector_number: resolved}
            else:
                row_siblings = {}
        rendered.append(
            mtgjson_card_to_payload(
                card,
                owned,
                scryfall_cards,
                row_siblings,
                display_lang,
                owned_by_finish=owned_by_finish,
            )
        )

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

    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT c.set_code, SUM(ci.quantity) AS owned_cards
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE c.set_code IS NOT NULL
        GROUP BY c.set_code
        """
    ).fetchall()
    owned_by_set = {(row["set_code"] or "").upper(): int(row["owned_cards"]) for row in rows}

    cached_codes = cached_set_codes()
    stats_cache = load_set_stats_cache()
    owned = owned_counts_by_scryfall(conn) if owned_by_set else {}
    pending_stats: dict[str, dict[str, Any]] = {}

    enriched: list[dict[str, Any]] = []
    for category in categories:
        sets = []
        for entry in category["sets"]:
            code = entry["code"]
            owned_cards = owned_by_set.get(code, 0)
            total_value_eur = None
            owned_value_eur = None

            cached_stats = stats_cache.get(code) or pending_stats.get(code)
            if cached_stats:
                total_value_eur = cached_stats.get("total_value_eur")

            if code in cached_codes:
                if cached_stats is None:
                    computed = compute_set_stats_fast(code, {})
                    if computed:
                        cached_stats = {
                            "total_cards": computed["total_cards"],
                            "total_value_eur": computed["total_value_eur"],
                        }
                        pending_stats[code] = cached_stats
                        stats_cache[code] = cached_stats
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
    if pending_stats:
        merge_set_stats_cache_entries(pending_stats)
    return enriched


def set_list_entry(set_code: str) -> dict[str, Any] | None:
    code = set_code.upper()
    for entry in load_set_list():
        if (entry.get("code") or "").upper() == code:
            return entry
    return None


def resolve_catalog_set_code(set_code: str) -> tuple[str, str | None]:
    code = (set_code or "").upper()
    if not code:
        return "", None
    entry = set_list_entry(code)
    if entry is None:
        return code, None
    parent = (entry.get("parentCode") or "").upper()
    if parent:
        return parent, code
    return code, None


def catalog_locations_for_set(set_code: str) -> list[dict[str, Any]]:
    catalog_code, section_code = resolve_catalog_set_code(set_code)
    if not catalog_code:
        return []

    locations: list[dict[str, Any]] = []
    for category in blocks_catalog():
        for set_entry in category.get("sets") or []:
            if (set_entry.get("code") or "").upper() != catalog_code:
                continue
            locations.append(
                {
                    "id": category["id"],
                    "label": category["label"],
                    "set_code": catalog_code,
                    "section_code": section_code,
                    "set_name": set_entry.get("name") or catalog_code,
                }
            )
    return locations


def owned_cards_for_set_code(conn, set_code: str) -> int:
    cards_table = catalog_table("cards")
    row = conn.execute(
        f"""
        SELECT SUM(ci.quantity) AS quantity
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
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


def owned_scryfall_ids(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT scryfall_id
        FROM collection_items
        WHERE quantity > 0
        ORDER BY scryfall_id
        """
    ).fetchall()
    return [row["scryfall_id"] for row in rows]


def scryfall_card_to_owned_payload(
    conn,
    row,
    card: dict[str, Any],
    *,
    display_lang: str = "merge",
    siblings: dict[str, str] | None = None,
    include_live_prices: bool = True,
) -> dict[str, Any]:
    finish = row["finish"]
    quantity = int(row["quantity"])
    display_card = resolve_display_card_db(conn, card, display_lang, siblings=siblings)
    prices = card_prices_eur(display_card)
    if include_live_prices:
        price_point = display_price_for(conn, display_card, finish)
    else:
        price_point = current_eur_price(display_card, finish)
    unit_price = float(price_point.price) if price_point else None
    type_line = display_card.get("type_line") or ""
    card_type, subtype = card_type_parts(type_line)

    return {
        "scryfall_id": card["id"],
        "display_scryfall_id": display_card["id"],
        "name": display_card.get("name"),
        "printed_name": display_card.get("printed_name"),
        "lang": display_card.get("lang"),
        "set_code": display_card.get("set"),
        "set_name": display_card.get("set_name"),
        "number": display_card.get("collector_number"),
        "rarity": display_card.get("rarity"),
        "type_line": type_line,
        "card_type": card_type,
        "subtype": subtype,
        "mana_cost": display_card.get("mana_cost"),
        "cmc": display_card.get("cmc") or 0,
        "colors": display_card.get("colors") or [],
        "color_identity": display_card.get("color_identity") or [],
        "finish": finish,
        "quantity": quantity,
        "owned": True,
        "image_url": catalog_image_url(display_card["id"]),
        "price_nonfoil": prices["nonfoil"],
        "price_foil": prices["foil"],
        "unit_price_eur": unit_price,
        "line_value_eur": (unit_price or 0) * quantity,
    }


def enrich_owned_cards_live_prices(conn, cards: list[dict[str, Any]]) -> None:
    if not cards:
        return
    pairs: list[tuple[str, str]] = []
    display_ids: dict[str, dict[str, Any]] = {}
    for card in cards:
        display_id = card.get("display_scryfall_id") or card["scryfall_id"]
        display_card = get_cached_card(conn, display_id)
        if not display_card:
            continue
        finish = card.get("finish") or "nonfoil"
        display_ids[card["scryfall_id"]] = display_card
        if current_eur_price(display_card, finish) is None:
            pairs.append((display_id, finish))

    snapshots = batch_latest_snapshots(conn, pairs)
    for card in cards:
        display_id = card.get("display_scryfall_id") or card["scryfall_id"]
        display_card = display_ids.get(card["scryfall_id"]) or get_cached_card(conn, display_id)
        if not display_card:
            continue
        finish = card.get("finish") or "nonfoil"
        price_point = current_eur_price(display_card, finish)
        if price_point is None:
            price_point = snapshots.get((display_id, finish))
            if price_point is None:
                price_point = display_price_for(conn, display_card, finish)
        unit_price = float(price_point.price) if price_point else card.get("unit_price_eur")
        card["unit_price_eur"] = unit_price
        card["line_value_eur"] = (unit_price or 0) * int(card.get("quantity") or 0)
        prices = card_prices_eur(display_card)
        card["price_nonfoil"] = prices["nonfoil"]
        card["price_foil"] = prices["foil"]
        card["price_source"] = display_price_source_label(display_card, finish, price_point)


def merge_owned_cards_by_scryfall(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    finish_priority = ("nonfoil", "foil", "etched")

    for card in cards:
        scryfall_id = card["scryfall_id"]
        finish = card["finish"]
        quantity = int(card["quantity"])

        if scryfall_id not in by_id:
            by_id[scryfall_id] = {
                **card,
                "finish_breakdown": {finish: quantity},
                "quantity": quantity,
            }
            continue

        entry = by_id[scryfall_id]
        breakdown = entry["finish_breakdown"]
        breakdown[finish] = breakdown.get(finish, 0) + quantity
        entry["quantity"] = int(entry["quantity"]) + quantity
        entry["line_value_eur"] = (entry.get("line_value_eur") or 0) + (card.get("line_value_eur") or 0)

    merged: list[dict[str, Any]] = []
    for entry in by_id.values():
        breakdown = entry["finish_breakdown"]
        entry["finish"] = next(
            (finish for finish in finish_priority if breakdown.get(finish, 0) > 0),
            entry.get("finish") or "nonfoil",
        )
        merged.append(entry)
    return merged


MY_COLLECTION_PAGE_SIZES = (50, 100, 200, 500)
_OWNED_COLLECTION_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_OWNED_COLLECTION_CACHE_LOCK = threading.Lock()
_OWNED_COLLECTION_CACHE_TTL = 300.0


def invalidate_owned_collection_cache() -> None:
    with _OWNED_COLLECTION_CACHE_LOCK:
        _OWNED_COLLECTION_CACHE.clear()


def _owned_collection_cache_key(sort: str, display_lang: str) -> str:
    return json.dumps({"sort": sort, "display_lang": display_lang}, sort_keys=True, separators=(",", ":"))


def _siblings_for_owned_line(
    conn,
    card: dict[str, Any],
    *,
    display_lang: str,
    siblings_by_set: dict[str, dict[str, dict[str, str]]],
    sibling_row_cache: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str]:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").strip()
    card_lang = str(card.get("lang") or "en").lower()

    if display_lang == "merge":
        siblings = siblings_by_set.get(set_code, {}).get(collector_number)
        if siblings:
            return siblings
        return {card_lang: card["id"]}

    if card_lang == display_lang:
        return {card_lang: card["id"]}

    cache_key = (set_code, collector_number)
    cached = sibling_row_cache.get(cache_key)
    if cached is not None:
        cached.setdefault(card_lang, card["id"])
        return cached
    resolved = language_sibling_ids_db(conn, card)
    sibling_row_cache[cache_key] = resolved
    return resolved


def _collect_needed_language_siblings(
    parsed_rows: list[tuple[Any, dict[str, Any]]],
    *,
    display_lang: str,
) -> dict[str, set[str]]:
    needed_by_set: dict[str, set[str]] = {}
    if display_lang == "merge":
        return needed_by_set
    for _, card in parsed_rows:
        card_lang = str(card.get("lang") or "en").lower()
        if card_lang == display_lang:
            continue
        set_code = str(card.get("set") or "").lower()
        collector_number = str(card.get("collector_number") or "").strip()
        if set_code and collector_number:
            needed_by_set.setdefault(set_code, set()).add(collector_number)
    return needed_by_set


def _load_owned_parsed_rows(
    conn,
    scryfall_ids: set[str] | None = None,
) -> list[tuple[Any, dict[str, Any]]]:
    cards_table = catalog_table("cards")
    if scryfall_ids:
        ids = sorted({sid for sid in scryfall_ids if sid})
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""
            SELECT ci.scryfall_id, ci.finish, ci.quantity, c.raw_json
            FROM collection_items ci
            JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
            WHERE ci.quantity > 0 AND ci.scryfall_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT ci.scryfall_id, ci.finish, ci.quantity, c.raw_json
            FROM collection_items ci
            JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
            WHERE ci.quantity > 0
            """
        ).fetchall()
    return [(row, json.loads(row["raw_json"])) for row in rows]


def _build_owned_cards_from_parsed_rows(
    conn,
    parsed_rows: list[tuple[Any, dict[str, Any]]],
    *,
    display_lang: str,
    include_live_prices: bool = False,
) -> list[dict[str, Any]]:
    siblings_by_set: dict[str, dict[str, dict[str, str]]] = {}
    sibling_row_cache: dict[tuple[str, str], dict[str, str]] = {}
    if display_lang == "merge":
        set_codes = {
            str(card.get("set") or "").lower()
            for _, card in parsed_rows
            if card.get("set")
        }
        siblings_by_set = {set_code: build_set_language_siblings(conn, set_code) for set_code in set_codes}
    else:
        needed_by_set = _collect_needed_language_siblings(parsed_rows, display_lang=display_lang)
        sibling_row_cache = build_language_siblings_for_collectors(conn, needed_by_set)

    cards: list[dict[str, Any]] = []
    for row, card in parsed_rows:
        siblings = _siblings_for_owned_line(
            conn,
            card,
            display_lang=display_lang,
            siblings_by_set=siblings_by_set,
            sibling_row_cache=sibling_row_cache,
        )
        cards.append(
            scryfall_card_to_owned_payload(
                conn,
                row,
                card,
                display_lang=display_lang,
                siblings=siblings,
                include_live_prices=include_live_prices,
            )
        )
    return merge_owned_cards_by_scryfall(cards)


def _build_owned_cards_for_scryfall_ids(
    conn,
    scryfall_ids: set[str],
    *,
    display_lang: str,
    include_live_prices: bool = False,
) -> list[dict[str, Any]]:
    parsed_rows = _load_owned_parsed_rows(conn, scryfall_ids)
    return _build_owned_cards_from_parsed_rows(
        conn,
        parsed_rows,
        display_lang=display_lang,
        include_live_prices=include_live_prices,
    )


def _build_owned_collection_cards_merged(
    conn,
    *,
    sort: str,
    display_lang: str,
    include_live_prices: bool = False,
) -> list[dict[str, Any]]:
    parsed_rows = _load_owned_parsed_rows(conn)
    cards = _build_owned_cards_from_parsed_rows(
        conn,
        parsed_rows,
        display_lang=display_lang,
        include_live_prices=include_live_prices,
    )
    sort_cards(cards, sort)
    return cards


def merged_owned_collection_cards(
    conn,
    *,
    sort: str = "name_asc",
    display_lang: str = "merge",
) -> list[dict[str, Any]]:
    cache_key = _owned_collection_cache_key(sort, display_lang)
    now = time.time()
    with _OWNED_COLLECTION_CACHE_LOCK:
        entry = _OWNED_COLLECTION_CACHE.get(cache_key)
        if entry is not None:
            cached_at, cards = entry
            if now - cached_at <= _OWNED_COLLECTION_CACHE_TTL:
                return cards
    cards = _build_owned_collection_cards_merged(conn, sort=sort, display_lang=display_lang)
    with _OWNED_COLLECTION_CACHE_LOCK:
        _OWNED_COLLECTION_CACHE[cache_key] = (now, cards)
    return cards


def list_owned_collection_cards(
    conn,
    *,
    sort: str = "name_asc",
    display_lang: str = "merge",
    limit: int | None = 100,
    offset: int = 0,
    filters: Any | None = None,
    on_progress: Any | None = None,
    use_index: bool = True,
) -> dict[str, Any]:
    if use_index:
        from .collection_index import MyCollectionFilters, list_owned_from_index

        page_size = limit if limit in MY_COLLECTION_PAGE_SIZES else 100
        if limit is None:
            page_size = 100
        return list_owned_from_index(
            conn,
            sort=sort,
            display_lang=display_lang,
            limit=page_size,
            offset=max(0, offset),
            filters=filters if isinstance(filters, MyCollectionFilters) else MyCollectionFilters(),
            on_progress=on_progress,
        )

    cards = merged_owned_collection_cards(conn, sort=sort, display_lang=display_lang)
    total = len(cards)
    if limit is None:
        page_size = total or 1
        offset = 0
        page_cards = cards
    else:
        page_size = limit if limit in MY_COLLECTION_PAGE_SIZES else 100
        offset = max(0, offset)
        if offset >= total and total > 0:
            offset = max(0, (total - 1) // page_size * page_size)
        page_cards = cards[offset : offset + page_size]
    enrich_owned_cards_live_prices(conn, page_cards)

    total_cards = sum(card["quantity"] for card in cards)
    total_value = sum(card.get("line_value_eur") or 0 for card in cards)
    page = (offset // page_size) + 1 if page_size else 1
    total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1

    return {
        "summary": {
            "unique_lines": total,
            "total_cards": total_cards,
            "total_value_eur": decimal_to_json(Decimal(str(total_value))),
        },
        "cards": page_cards,
        "pagination": {
            "total": total,
            "offset": offset,
            "page_size": page_size,
            "page": page,
            "total_pages": total_pages,
        },
    }
