from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .local_cache import load_deck, load_deck_list, load_set_list, deck_json_path


MTGJSON_BASE_URL = "https://mtgjson.com/api/v5"
ALL_PRICES_GZ_URL = f"{MTGJSON_BASE_URL}/AllPrices.json.gz"
ALL_PRICES_TODAY_GZ_URL = f"{MTGJSON_BASE_URL}/AllPricesToday.json.gz"
DECK_LIST_GZ_URL = f"{MTGJSON_BASE_URL}/DeckList.json.gz"
USER_AGENT = "mtg-project-pwa/0.1"
FINISH_TO_MTGJSON = {
    "nonfoil": "normal",
    "foil": "foil",
    "etched": "etched",
}
FINISH_FROM_MTGJSON = {value: key for key, value in FINISH_TO_MTGJSON.items()}


class MtgjsonError(RuntimeError):
    pass


def mtgjson_uuid_for_scryfall_card(card: dict[str, Any]) -> str | None:
    set_code = card.get("set")
    scryfall_id = card.get("id")
    collector_number = card.get("collector_number")
    if not set_code or not scryfall_id:
        return None

    set_payload = fetch_json(f"{MTGJSON_BASE_URL}/{set_code.upper()}.json")
    cards = ((set_payload.get("data") or {}).get("cards")) or []

    for mtgjson_card in cards:
        identifiers = mtgjson_card.get("identifiers") or {}
        if identifiers.get("scryfallId") == scryfall_id:
            return mtgjson_card.get("uuid")

    # Some localized Scryfall cards do not map 1:1. Falling back to collector
    # number is useful when the print is unique within a set.
    if collector_number:
        for mtgjson_card in cards:
            if mtgjson_card.get("number") == collector_number:
                return mtgjson_card.get("uuid")
    return None


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise MtgjsonError(f"MTGJSON HTTP {error.code}: {details}") from error
    except URLError as error:
        raise MtgjsonError(f"MTGJSON request failed: {error.reason}") from error


def fetch_gzip_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(gzip.decompress(response.read()).decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise MtgjsonError(f"MTGJSON HTTP {error.code}: {details}") from error
    except URLError as error:
        raise MtgjsonError(f"MTGJSON request failed: {error.reason}") from error


def filter_decks(
    query: str,
    *,
    commander_only: bool = True,
    hide_collector: bool = False,
    extension: str = "",
) -> list[dict[str, Any]]:
    decks = load_deck_list()
    normalized_query = query.strip().lower()
    normalized_extension = extension.strip().upper()

    if commander_only:
        decks = [deck for deck in decks if deck.get("type") == "Commander Deck"]
    if hide_collector:
        decks = [
            deck
            for deck in decks
            if "collector" not in f"{deck.get('name', '')} {deck.get('fileName', '')}".lower()
        ]
    if normalized_extension:
        decks = [deck for deck in decks if (deck.get("code") or "").upper() == normalized_extension]

    if normalized_query:
        tokens = normalized_query.split()
        decks = [
            deck
            for deck in decks
            if all(
                token in f"{deck.get('name', '')} {deck.get('code', '')} {deck.get('type', '')}".lower()
                for token in tokens
            )
        ]
    elif not commander_only:
        preferred_types = {"Commander Deck", "Challenger Deck", "Theme Deck", "Starter Deck"}
        decks = [deck for deck in decks if deck.get("type") in preferred_types]

    return decks


_SET_NAME_MAP: dict[str, str] | None = None


def set_name_map() -> dict[str, str]:
    global _SET_NAME_MAP
    if _SET_NAME_MAP is None:
        _SET_NAME_MAP = {
            (entry.get("code") or "").upper(): entry.get("name") or entry.get("code") or ""
            for entry in load_set_list()
            if entry.get("code")
        }
    return _SET_NAME_MAP


def list_deck_extensions(
    *,
    commander_only: bool = True,
    hide_collector: bool = False,
) -> list[dict[str, str]]:
    decks = filter_decks("", commander_only=commander_only, hide_collector=hide_collector)
    codes = sorted({(deck.get("code") or "").upper() for deck in decks if deck.get("code")})
    names = set_name_map()
    extensions = [{"code": code, "name": names.get(code) or code} for code in codes]
    return sorted(extensions, key=lambda entry: entry["name"].lower())


def search_decks(
    query: str,
    limit: int = 30,
    offset: int = 0,
    commander_only: bool = True,
    hide_collector: bool = False,
    extension: str = "",
    sort: str = "release_desc",
) -> tuple[list[dict[str, Any]], int]:
    sorted_decks = sort_decks(
        filter_decks(
            query,
            commander_only=commander_only,
            hide_collector=hide_collector,
            extension=extension,
        ),
        sort,
    )
    summaries = [
        {
            "code": deck.get("code"),
            "file_name": deck.get("fileName"),
            "name": deck.get("name"),
            "release_date": deck.get("releaseDate"),
            "type": deck.get("type"),
            "source": deck.get("source"),
        }
        for deck in sorted_decks
    ]
    total = len(summaries)
    return summaries[offset : offset + limit], total


def sort_decks(decks: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "release_asc":
        return sorted(decks, key=lambda deck: (deck.get("releaseDate") or "", deck.get("name") or ""))
    if sort == "extension":
        return sorted(decks, key=lambda deck: (deck.get("code") or "", deck.get("releaseDate") or "", deck.get("name") or ""))
    if sort == "name":
        return sorted(decks, key=lambda deck: (deck.get("name") or "", deck.get("releaseDate") or ""))
    return sorted(decks, key=lambda deck: (deck.get("releaseDate") or "", deck.get("name") or ""), reverse=True)


def deck_owned_status(conn, file_name: str, deck: dict[str, Any]) -> dict[str, Any]:
    from .database import is_deck_owned, owned_counts_by_card_finish

    deck_cards = importable_deck_cards(deck)
    total_cards = sum(card["quantity"] for card in deck_cards)
    explicit = is_deck_owned(conn, file_name)
    if not deck_cards:
        return {
            "owned": explicit,
            "owned_source": "manual" if explicit else "none",
            "collected_cards": 0,
            "total_cards": 0,
        }

    owned = owned_counts_by_card_finish(conn)
    collected_cards = 0
    fully_collected = True
    for card in deck_cards:
        have = owned.get((card["scryfall_id"], card["finish"]), 0)
        if have < card["quantity"]:
            fully_collected = False
        collected_cards += min(have, card["quantity"])

    if explicit:
        source = "manual"
    elif fully_collected:
        source = "collection"
    else:
        source = "none"

    return {
        "owned": explicit,
        "fully_collected": fully_collected,
        "owned_source": source,
        "collected_cards": collected_cards,
        "total_cards": total_cards,
    }


def fetch_deck(file_name: str) -> dict[str, Any]:
    return load_deck(file_name)


def deck_file_in_catalog(file_name: str) -> bool:
    if deck_json_path(file_name).exists():
        return True
    return any(deck.get("fileName") == file_name for deck in load_deck_list())


def deck_thumbnail_info(deck: dict[str, Any]) -> dict[str, Any] | None:
    from .local_cache import catalog_image_url

    for section in ("commander", "mainBoard"):
        for card in deck.get(section) or []:
            scryfall_id = (card.get("identifiers") or {}).get("scryfallId")
            if not scryfall_id:
                continue
            return {
                "scryfall_id": scryfall_id,
                "name": card.get("name") or "",
                "image_url": catalog_image_url(scryfall_id),
                "kind": "commander" if section == "commander" else "card",
            }
    return None


def importable_deck_cards(deck: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for section in ("commander", "mainBoard", "sideBoard"):
        for card in deck.get(section) or []:
            identifiers = card.get("identifiers") or {}
            scryfall_id = identifiers.get("scryfallId")
            if not scryfall_id:
                continue
            cards.append(
                {
                    "scryfall_id": scryfall_id,
                    "mtgjson_uuid": card.get("uuid"),
                    "name": card.get("name"),
                    "quantity": int(card.get("count") or 1),
                    "finish": "foil" if card.get("isFoil") else "nonfoil",
                    "section": section,
                    "set_code": card.get("setCode"),
                    "collector_number": card.get("number"),
                }
            )
    return cards


def deck_cards_by_section(deck: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for card in importable_deck_cards(deck):
        grouped.setdefault(card["section"], []).append(card)
    return grouped


def deck_summary(deck: dict[str, Any], file_name: str) -> dict[str, Any]:
    cards = importable_deck_cards(deck)
    return {
        "file_name": file_name,
        "name": deck.get("name"),
        "code": deck.get("code"),
        "type": deck.get("type"),
        "release_date": deck.get("releaseDate"),
        "source": deck.get("source"),
        "card_lines": len(cards),
        "card_count": sum(card["quantity"] for card in cards),
        "foil_count": sum(card["quantity"] for card in cards if card["finish"] == "foil"),
    }


def extract_price_entry(uuid: str) -> dict[str, Any] | None:
    local_path = os.environ.get("MTGJSON_ALL_PRICES")
    if local_path:
        path = Path(local_path)
        if not path.exists():
            raise MtgjsonError(f"MTGJSON_ALL_PRICES introuvable: {path}")
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            return extract_price_entry_from_text_stream(handle, uuid)

    request = Request(ALL_PRICES_GZ_URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=90) as response:
            with gzip.GzipFile(fileobj=response) as gzip_file:
                return extract_price_entry_from_text_stream(TextChunkReader(gzip_file), uuid)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise MtgjsonError(f"MTGJSON prices HTTP {error.code}: {details}") from error
    except URLError as error:
        raise MtgjsonError(f"MTGJSON prices request failed: {error.reason}") from error


def extract_price_entries(
    uuids: list[str],
    *,
    source: str = "all",
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    remaining = set(uuids)
    if not remaining:
        return {}

    if source == "today":
        local_path = os.environ.get("MTGJSON_ALL_PRICES_TODAY")
        remote_url = ALL_PRICES_TODAY_GZ_URL
    else:
        local_path = os.environ.get("MTGJSON_ALL_PRICES")
        remote_url = ALL_PRICES_GZ_URL

    if local_path:
        path = Path(local_path)
        if not path.exists():
            raise MtgjsonError(f"Fichier prix MTGJSON introuvable: {path}")
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            return extract_price_entries_from_text_stream(handle, remaining, on_progress=on_progress)

    request = Request(remote_url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=180) as response:
            with gzip.GzipFile(fileobj=response) as gzip_file:
                return extract_price_entries_from_text_stream(
                    TextChunkReader(gzip_file),
                    remaining,
                    on_progress=on_progress,
                )
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise MtgjsonError(f"MTGJSON prices HTTP {error.code}: {details}") from error
    except URLError as error:
        raise MtgjsonError(f"MTGJSON prices request failed: {error.reason}") from error


def extract_price_entries_today(
    uuids: list[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    return extract_price_entries(uuids, source="today", on_progress=on_progress)


class TextChunkReader:
    def __init__(self, gzip_file: gzip.GzipFile) -> None:
        self.gzip_file = gzip_file

    def read(self, size: int) -> str:
        return self.gzip_file.read(size).decode("utf-8")


def extract_price_entry_from_text_stream(stream: Any, uuid: str) -> dict[str, Any] | None:
    target = f'"{uuid}":'
    buffer = ""
    found = False
    object_text = ""
    depth = 0
    in_string = False
    escape = False
    parsing_object = False

    while True:
        chunk = stream.read(1024 * 128)
        if not chunk:
            return None

        if not found:
            buffer += chunk
            index = buffer.find(target)
            if index == -1:
                buffer = buffer[-len(target) :]
                continue
            found = True
            chunk = buffer[index + len(target) :]
            buffer = ""

        for char in chunk:
            if not parsing_object:
                if char.isspace():
                    continue
                if char != "{":
                    raise MtgjsonError("Format AllPrices inattendu pour l'entree demandee.")
                parsing_object = True
                depth = 1
                object_text = "{"
                continue

            object_text += char
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(object_text)


def extract_price_entries_from_text_stream(
    stream: Any,
    uuids: set[str],
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    # AllPrices is a giant JSON object. This parser walks the decompressed text
    # once and captures only objects whose key is in the requested UUID set.
    results: dict[str, dict[str, Any]] = {}
    initial_total = len(uuids)
    current_key = ""
    object_text = ""
    depth = 0
    in_string = False
    escape = False
    reading_key = False
    parsing_target_object = False
    target_key: str | None = None
    stack: list[str] = []

    while True:
        chunk = stream.read(1024 * 128)
        if not chunk:
            return results

        for char in chunk:
            if parsing_target_object:
                object_text += char
                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                else:
                    if char == '"':
                        in_string = True
                    elif char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0 and target_key is not None:
                            results[target_key] = json.loads(object_text)
                            uuids.discard(target_key)
                            if on_progress is not None:
                                on_progress(len(results), initial_total)
                            if stack and stack[-1] == target_key:
                                stack.pop()
                            if not uuids:
                                return results
                            parsing_target_object = False
                            target_key = None
                            object_text = ""
                continue

            if in_string:
                if escape:
                    if reading_key:
                        current_key += char
                    escape = False
                elif char == "\\":
                    if reading_key:
                        current_key += char
                    escape = True
                elif char == '"':
                    in_string = False
                    reading_key = False
                elif reading_key:
                    current_key += char
                continue

            if char == '"':
                in_string = True
                reading_key = True
                current_key = ""
                continue

            if char == "{":
                stack.append(current_key)
                if len(stack) == 3 and stack[0] == "" and stack[1] == "data" and stack[2] in uuids:
                    parsing_target_object = True
                    target_key = stack[2]
                    object_text = "{"
                    depth = 1
                current_key = ""
                continue

            if char == "}":
                if stack:
                    stack.pop()
                current_key = ""
                continue


def normalize_price_points(
    scryfall_id: str,
    price_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    paper = price_entry.get("paper") or {}

    for provider, provider_data in paper.items():
        currency = provider_data.get("currency")
        retail = provider_data.get("retail") or {}
        for mtgjson_finish, dated_prices in retail.items():
            finish = FINISH_FROM_MTGJSON.get(mtgjson_finish, mtgjson_finish)
            if not isinstance(dated_prices, dict):
                continue
            for snapshot_date, price in dated_prices.items():
                if price in (None, ""):
                    continue
                points.append(
                    {
                        "scryfall_id": scryfall_id,
                        "currency": currency,
                        "finish": finish,
                        "price": float(price),
                        "source": f"mtgjson-{provider}",
                        "snapshot_date": snapshot_date,
                        "collected_at": now,
                    }
                )
    return points


def market_summaries(points: list[dict[str, Any]], finish: str) -> list[dict[str, Any]]:
    by_market: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for point in points:
        if point["finish"] != finish:
            continue
        key = (point["source"], point["currency"], point["finish"])
        by_market.setdefault(key, []).append(point)

    summaries: list[dict[str, Any]] = []
    for (source, currency, point_finish), market_points in by_market.items():
        sorted_points = sorted(market_points, key=lambda point: point["snapshot_date"])
        latest = sorted_points[-1]
        summaries.append(
            {
                "source": source,
                "currency": currency,
                "finish": point_finish,
                "latest_price": latest["price"],
                "latest_date": latest["snapshot_date"],
                "first_date": sorted_points[0]["snapshot_date"],
                "point_count": len(sorted_points),
            }
        )
    return sorted(summaries, key=lambda item: (item["currency"] != "EUR", item["source"]))
