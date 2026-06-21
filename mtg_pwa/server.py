from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .database import (
    DEFAULT_DB_PATH,
    add_collection_item,
    card_summary,
    cached_mtgjson_price_entry,
    cached_mtgjson_uuid,
    collection_card_ids,
    connect,
    delete_collection_item,
    get_cached_card,
    init_db,
    latest_snapshot,
    list_collection,
    price_history,
    price_periods,
    save_card,
    save_cards,
    save_external_price_snapshots,
    save_fallback_price_snapshot,
    save_mtgjson_price_entry,
    save_mtgjson_uuid,
    save_price_snapshots,
    update_collection_item,
)
from .mtgjson import (
    MtgjsonError,
    deck_cards_by_section,
    deck_summary,
    extract_price_entry,
    extract_price_entries,
    fetch_deck,
    importable_deck_cards,
    market_summaries,
    mtgjson_uuid_for_scryfall_card,
    normalize_price_points,
    search_decks,
)
from .prices import current_eur_price
from .scryfall import ScryfallClient, ScryfallError


VALID_FINISHES = {"nonfoil", "foil", "etched"}
VALID_CONDITIONS = {"mint", "near_mint", "excellent", "good", "played", "poor"}
PRELOAD_STATUS: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "decks_total": 0,
    "decks_processed": 0,
    "unique_uuids": 0,
    "cached_uuids": 0,
    "fetched_uuids": 0,
    "missing_uuids": 0,
    "scryfall_cards_cached": 0,
    "points": 0,
    "snapshots_written": 0,
}
PRELOAD_LOCK = threading.Lock()


class MvpRequestHandler(BaseHTTPRequestHandler):
    server_version = "MTGPWA/0.1"
    static_dir = Path(__file__).parent / "static"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, parse_qs(parsed.query))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PATCH", parsed.path, parse_qs(parsed.query))

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, parse_qs(parsed.query))

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("MTG_PWA_DEBUG"):
            super().log_message(format, *args)

    def handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        try:
            if method == "GET" and path == "/api/health":
                self.json_response({"status": "ok"})
                return
            if method == "GET" and path == "/api/search":
                self.search_cards(query)
                return
            if method == "GET" and path == "/api/collection":
                self.collection()
                return
            if method == "POST" and path == "/api/collection":
                self.add_to_collection()
                return
            if method == "POST" and path == "/api/snapshots/refresh":
                self.refresh_snapshots()
                return
            if method == "GET" and path == "/api/decks/search":
                self.search_decks(query)
                return
            if method == "POST" and path == "/api/decks/import":
                self.import_deck()
                return
            if method == "GET" and path == "/api/decks/detail":
                self.deck_detail(query)
                return
            if method == "POST" and path == "/api/preload/commander-prices":
                self.start_commander_preload()
                return
            if method == "GET" and path == "/api/preload/commander-prices":
                self.commander_preload_status()
                return

            segments = path.strip("/").split("/")
            if len(segments) == 3 and segments[:2] == ["api", "collection"]:
                item_id = int(segments[2])
                if method == "PATCH":
                    self.update_collection(item_id)
                    return
                if method == "DELETE":
                    self.delete_from_collection(item_id)
                    return
            if len(segments) == 4 and segments[:2] == ["api", "cards"] and segments[3] == "prices":
                if method == "GET":
                    self.card_prices(segments[2], query)
                    return
            if len(segments) == 4 and segments[:2] == ["api", "cards"] and segments[3] == "detail":
                if method == "GET":
                    self.card_detail(segments[2], query)
                    return

            self.json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.json_response({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
        except ScryfallError as error:
            self.json_response({"error": str(error)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as error:  # noqa: BLE001 - server should return JSON errors.
            self.json_response({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def search_cards(self, query: dict[str, list[str]]) -> None:
        search = one(query, "q", "").strip()
        if not search:
            raise ValueError("Le parametre q est requis.")

        lang = one(query, "lang", "fr")
        limit = int(one(query, "limit", "24"))
        finish = one(query, "finish", "nonfoil")
        serialized = one(query, "serialized", "false").lower() in {"1", "true", "yes", "on"}
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")

        client = ScryfallClient()
        cards = client.search_cards(search, lang=lang, limit=limit, serialized=serialized)
        with open_db() as conn:
            save_cards(conn, cards)
            for card in cards:
                ensure_price_fallback(conn, client, card, finish)
            conn.commit()
            response = [card_summary(conn, card, finish) for card in cards]
        self.json_response({"cards": response})

    def collection(self) -> None:
        with open_db() as conn:
            self.json_response(list_collection(conn))

    def search_decks(self, query: dict[str, list[str]]) -> None:
        search = one(query, "q", "").strip()
        limit = int(one(query, "limit", "30"))
        commander_only = one(query, "commander_only", "true").lower() in {"1", "true", "yes", "on"}
        hide_collector = one(query, "hide_collector", "false").lower() in {"1", "true", "yes", "on"}
        sort = one(query, "sort", "release_desc")
        decks = search_decks(
            search,
            limit=limit,
            commander_only=commander_only,
            hide_collector=hide_collector,
            sort=sort,
        )
        with open_db() as conn:
            response_decks = []
            for deck in decks:
                deck_payload = fetch_deck(deck["file_name"])
                enriched = dict(deck)
                enriched["price_estimate"] = deck_menu_price_estimate(conn, deck_payload)
                response_decks.append(enriched)
        self.json_response({"decks": response_decks})

    def deck_detail(self, query: dict[str, list[str]]) -> None:
        file_name = one(query, "file_name", "").strip()
        if not file_name:
            raise ValueError("file_name est requis.")

        deck = fetch_deck(file_name)
        grouped_cards = deck_cards_by_section(deck)
        deck_cards = importable_deck_cards(deck)
        scryfall_ids = sorted({card["scryfall_id"] for card in deck_cards})
        client = ScryfallClient()

        with open_db() as conn:
            scryfall_cards = client.collection(scryfall_ids) if scryfall_ids else []
            save_cards(conn, scryfall_cards)
            cards_by_id = {card["id"]: card for card in scryfall_cards}
            mtgjson_points, mtgjson_status = enrich_deck_mtgjson_prices(conn, deck_cards)
            valuation = deck_valuation(conn, deck_cards, cards_by_id, mtgjson_points)
            commanders = [
                card_summary(conn, cards_by_id[card["scryfall_id"]], card["finish"])
                for card in grouped_cards.get("commander", [])
                if card["scryfall_id"] in cards_by_id
            ]

        self.json_response(
            {
                "deck": deck_summary(deck, file_name),
                "commanders": commanders,
                "cards_by_section": grouped_cards,
                "valuation": valuation,
                "mtgjson": mtgjson_status,
            }
        )

    def import_deck(self) -> None:
        payload = self.read_json()
        file_name = str(payload.get("file_name") or "").strip()
        if not file_name:
            raise ValueError("file_name est requis.")

        deck = fetch_deck(file_name)
        deck_cards = importable_deck_cards(deck)
        if not deck_cards:
            raise ValueError("Aucune carte importable trouvee dans ce deck.")

        client = ScryfallClient()
        unique_ids = sorted({card["scryfall_id"] for card in deck_cards})
        scryfall_cards = client.collection(unique_ids)
        cards_by_id = {card["id"]: card for card in scryfall_cards}

        imported = 0
        missing: list[dict[str, Any]] = []
        with open_db() as conn:
            for card in scryfall_cards:
                save_card(conn, card)
                save_price_snapshots(conn, card)

            for deck_card in deck_cards:
                scryfall_id = deck_card["scryfall_id"]
                scryfall_card = cards_by_id.get(scryfall_id)
                if scryfall_card is None:
                    missing.append(deck_card)
                    continue
                save_mtgjson_uuid(
                    conn,
                    scryfall_id=scryfall_id,
                    mtgjson_uuid=deck_card["mtgjson_uuid"],
                    set_code=deck_card["set_code"],
                    collector_number=deck_card["collector_number"],
                )
                ensure_price_fallback(conn, client, scryfall_card, deck_card["finish"])
                add_collection_item(
                    conn,
                    scryfall_id=scryfall_id,
                    quantity=deck_card["quantity"],
                    finish=deck_card["finish"],
                    condition="near_mint",
                    language=scryfall_card.get("lang"),
                    purchase_price=None,
                    purchase_currency="EUR",
                    purchase_date=None,
                    notes=f"Import precon: {deck.get('name')}",
                )
                imported += deck_card["quantity"]

            response = list_collection(conn)
            response["deck_import"] = {
                "deck": deck_summary(deck, file_name),
                "imported_cards": imported,
                "missing_cards": missing,
            }
        self.json_response(response, status=HTTPStatus.CREATED)

    def start_commander_preload(self) -> None:
        payload = self.read_json(default={})
        limit = payload.get("limit")
        limit_value = int(limit) if limit not in (None, "") else None
        started = start_preload_job(limit=limit_value)
        status = preload_status()
        status["started_now"] = started
        self.json_response(status, status=HTTPStatus.ACCEPTED)

    def commander_preload_status(self) -> None:
        self.json_response(preload_status())

    def add_to_collection(self) -> None:
        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")

        quantity = max(1, int(payload.get("quantity") or 1))
        finish = str(payload.get("finish") or "nonfoil")
        condition = str(payload.get("condition") or "near_mint")
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")
        if condition not in VALID_CONDITIONS:
            raise ValueError("Etat invalide.")

        with open_db() as conn:
            card = ensure_card(conn, scryfall_id)
            ensure_price_fallback(conn, ScryfallClient(), card, finish)
            conn.commit()
            item_id = add_collection_item(
                conn,
                scryfall_id=scryfall_id,
                quantity=quantity,
                finish=finish,
                condition=condition,
                language=payload.get("language") or card.get("lang"),
                purchase_price=optional_float(payload.get("purchase_price")),
                purchase_currency=str(payload.get("purchase_currency") or "EUR"),
                purchase_date=payload.get("purchase_date"),
                notes=payload.get("notes"),
            )
            response = list_collection(conn)
            response["created_item_id"] = item_id
        self.json_response(response, status=HTTPStatus.CREATED)

    def update_collection(self, item_id: int) -> None:
        payload = self.read_json()
        if "quantity" in payload:
            payload["quantity"] = max(1, int(payload["quantity"]))
        if "finish" in payload and payload["finish"] not in VALID_FINISHES:
            raise ValueError("Finition invalide.")
        if "condition" in payload and payload["condition"] not in VALID_CONDITIONS:
            raise ValueError("Etat invalide.")
        if "purchase_price" in payload:
            payload["purchase_price"] = optional_float(payload["purchase_price"])

        with open_db() as conn:
            updated = update_collection_item(conn, item_id, payload)
            if not updated:
                self.json_response({"error": "Collection item not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.json_response(list_collection(conn))

    def delete_from_collection(self, item_id: int) -> None:
        with open_db() as conn:
            deleted = delete_collection_item(conn, item_id)
            if not deleted:
                self.json_response({"error": "Collection item not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.json_response(list_collection(conn))

    def refresh_snapshots(self) -> None:
        payload = self.read_json(default={})
        collection_only = bool(payload.get("collection_only", True))
        refreshed = 0
        snapshot_count = 0
        client = ScryfallClient()

        with open_db() as conn:
            if collection_only:
                card_ids = collection_card_ids(conn)
            else:
                rows = conn.execute("SELECT scryfall_id FROM cards ORDER BY updated_at DESC LIMIT 100").fetchall()
                card_ids = [row["scryfall_id"] for row in rows]

            for scryfall_id in card_ids:
                card = client.card(scryfall_id)
                save_card(conn, card)
                snapshot_count += save_price_snapshots(conn, card)
                for finish in card.get("finishes") or ["nonfoil"]:
                    if finish in VALID_FINISHES:
                        snapshot_count += ensure_price_fallback(conn, client, card, finish)
                refreshed += 1
                client.throttle()
            conn.commit()

            response = list_collection(conn)
            response["refresh"] = {
                "cards_refreshed": refreshed,
                "snapshots_written": snapshot_count,
                "collection_only": collection_only,
            }
        self.json_response(response)

    def card_prices(self, scryfall_id: str, query: dict[str, list[str]]) -> None:
        finish = one(query, "finish", "nonfoil")
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")

        with open_db() as conn:
            try:
                card = ensure_card(conn, scryfall_id)
                save_price_snapshots(conn, card)
                ensure_price_fallback(conn, ScryfallClient(), card, finish)
                conn.commit()
            except ScryfallError:
                card = get_cached_card(conn, scryfall_id)
                if card is None:
                    raise

            self.json_response(
                {
                    "card": card_summary(conn, card, finish),
                    "history": price_history(conn, scryfall_id, finish),
                }
            )

    def card_detail(self, scryfall_id: str, query: dict[str, list[str]]) -> None:
        finish = one(query, "finish", "nonfoil")
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")

        client = ScryfallClient()
        rulings: list[dict[str, Any]] = []
        with open_db() as conn:
            try:
                card = ensure_card(conn, scryfall_id)
                save_price_snapshots(conn, card)
                ensure_price_fallback(conn, client, card, finish)
                conn.commit()
                rulings = client.rulings(scryfall_id)
            except ScryfallError:
                card = get_cached_card(conn, scryfall_id)
                if card is None:
                    raise

            summary = card_summary(conn, card, finish)
            effective_finish = summary.get("display_finish") or finish
            mtgjson_points, mtgjson_status = enrich_mtgjson_prices(conn, card)
            history = price_history(conn, scryfall_id, effective_finish)
            self.json_response(
                {
                    "card": summary,
                    "details": card_details(card),
                    "rulings": rulings_to_json(rulings),
                    "history": history,
                    "periods": price_periods(history),
                    "markets": market_summaries(mtgjson_points, effective_finish),
                    "mtgjson": mtgjson_status,
                }
            )

    def read_json(self, default: Any | None = None) -> Any:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length == 0:
            if default is not None:
                return default
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def json_response(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            relative = Path("index.html")
        else:
            relative = Path(path.lstrip("/"))

        target = (self.static_dir / relative).resolve()
        if not str(target).startswith(str(self.static_dir.resolve())) or not target.exists():
            target = self.static_dir / "index.html"

        data = target.read_bytes()
        content_type, _ = mimetypes.guess_type(target)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def one(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def open_db():
    db_path = Path(os.environ.get("MTG_PWA_DB", DEFAULT_DB_PATH))
    conn = connect(db_path)
    init_db(conn)
    return conn


def ensure_card(conn, scryfall_id: str) -> dict[str, Any]:
    card = get_cached_card(conn, scryfall_id)
    if card is not None:
        return card

    client = ScryfallClient()
    card = client.card(scryfall_id)
    save_card(conn, card)
    save_price_snapshots(conn, card)
    conn.commit()
    return card


def ensure_price_fallback(conn, client: ScryfallClient, card: dict[str, Any], finish: str) -> int:
    if current_eur_price(card, finish) is not None:
        return 0
    if latest_snapshot(conn, card["id"], finish) is not None:
        return 0

    set_code = card.get("set")
    collector_number = card.get("collector_number")
    if not set_code or not collector_number or card.get("lang") == "en":
        return 0

    try:
        english_print = client.card_by_set_number_lang(set_code, collector_number, "en")
    except ScryfallError:
        return 0

    fallback_price = current_eur_price(english_print, finish)
    if fallback_price is None:
        return 0

    save_fallback_price_snapshot(
        conn,
        scryfall_id=card["id"],
        finish=finish,
        price=fallback_price.price,
        source=f"scryfall-cardmarket-en-print:{english_print['id']}",
        source_updated_at=english_print.get("updated_at"),
    )
    return 1


def enrich_mtgjson_prices(conn, card: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status: dict[str, Any] = {
        "enabled": True,
        "source": "MTGJSON AllPrices",
        "note": "AllPrices enrichit l'historique disponible dans le fichier courant MTGJSON.",
    }
    try:
        mtgjson_uuid = cached_mtgjson_uuid(conn, card["id"])
        if mtgjson_uuid is None:
            mtgjson_uuid = mtgjson_uuid_for_scryfall_card(card)
            if mtgjson_uuid is None:
                status.update({"available": False, "message": "UUID MTGJSON introuvable pour cette impression."})
                return [], status
            save_mtgjson_uuid(
                conn,
                scryfall_id=card["id"],
                mtgjson_uuid=mtgjson_uuid,
                set_code=card.get("set"),
                collector_number=card.get("collector_number"),
            )

        price_entry = cached_mtgjson_price_entry(conn, mtgjson_uuid)
        cache_hit = price_entry is not None
        if price_entry is None:
            price_entry = extract_price_entry(mtgjson_uuid)
            if price_entry is None:
                status.update({"available": False, "mtgjson_uuid": mtgjson_uuid, "message": "Prix MTGJSON introuvables."})
                conn.commit()
                return [], status
            save_mtgjson_price_entry(conn, mtgjson_uuid, price_entry)

        points = normalize_price_points(card["id"], price_entry)
        inserted = save_external_price_snapshots(conn, points)
        conn.commit()
        status.update(
            {
                "available": True,
                "mtgjson_uuid": mtgjson_uuid,
                "cache_hit": cache_hit,
                "points": len(points),
                "snapshots_written": inserted,
            }
        )
        return points, status
    except MtgjsonError as error:
        status.update({"available": False, "message": str(error)})
        return [], status


def enrich_deck_mtgjson_prices(conn, deck_cards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    uuids = sorted({card["mtgjson_uuid"] for card in deck_cards if card.get("mtgjson_uuid")})
    status: dict[str, Any] = {
        "enabled": True,
        "source": "MTGJSON AllPrices",
        "requested_uuids": len(uuids),
    }
    if not uuids:
        status.update({"available": False, "message": "Aucun UUID MTGJSON dans ce deck."})
        return [], status

    entries: dict[str, dict[str, Any]] = {}
    missing_uuids: list[str] = []
    for uuid in uuids:
        cached = cached_mtgjson_price_entry(conn, uuid)
        if cached is None:
            missing_uuids.append(uuid)
        else:
            entries[uuid] = cached

    try:
        fetched_entries = extract_price_entries(missing_uuids)
    except MtgjsonError as error:
        status.update({"available": False, "message": str(error), "cache_hits": len(entries)})
        return [], status

    for uuid, entry in fetched_entries.items():
        save_mtgjson_price_entry(conn, uuid, entry)
        entries[uuid] = entry

    points: list[dict[str, Any]] = []
    for deck_card in deck_cards:
        entry = entries.get(deck_card.get("mtgjson_uuid"))
        if entry is None:
            continue
        points.extend(normalize_price_points(deck_card["scryfall_id"], entry))

    inserted = save_external_price_snapshots(conn, points)
    conn.commit()
    status.update(
        {
            "available": bool(points),
            "cache_hits": len(uuids) - len(missing_uuids),
            "fetched": len(fetched_entries),
            "missing_uuids": len(set(missing_uuids) - set(fetched_entries)),
            "points": len(points),
            "snapshots_written": inserted,
        }
    )
    return points, status


def deck_valuation(
    conn,
    deck_cards: list[dict[str, Any]],
    cards_by_id: dict[str, dict[str, Any]],
    mtgjson_points: list[dict[str, Any]],
) -> dict[str, Any]:
    total = Decimal("0")
    priced_cards = 0
    missing_cards = 0
    missing_lines: list[dict[str, Any]] = []

    for deck_card in deck_cards:
        card = cards_by_id.get(deck_card["scryfall_id"])
        quantity = int(deck_card["quantity"])
        if card is None:
            missing_cards += quantity
            missing_lines.append(missing_deck_line(deck_card, "Carte Scryfall introuvable."))
            continue

        summary = card_summary(conn, card, deck_card["finish"])
        price = summary.get("price")
        if price and price.get("currency") == "EUR" and price.get("price") is not None:
            total += Decimal(str(price["price"])) * quantity
            priced_cards += quantity
        else:
            missing_cards += quantity
            missing_lines.append(missing_deck_line(deck_card, "Prix EUR indisponible."))

    history = deck_history(deck_cards, mtgjson_points)
    return {
        "current_total_eur": float(total),
        "priced_cards": priced_cards,
        "missing_cards": missing_cards,
        "missing_lines": missing_lines,
        "history": history,
        "history_source": "MTGJSON cardmarket EUR",
    }


def deck_menu_price_estimate(conn, deck: dict[str, Any]) -> dict[str, Any]:
    total = Decimal("0")
    priced_cards = 0
    missing_cards = 0
    latest_date: str | None = None

    for deck_card in importable_deck_cards(deck):
        quantity = int(deck_card["quantity"])
        entry = cached_mtgjson_price_entry(conn, deck_card["mtgjson_uuid"])
        price_point = latest_cardmarket_price(entry, deck_card["finish"]) if entry else None
        if price_point is None:
            missing_cards += quantity
            continue
        total += Decimal(str(price_point["price"])) * quantity
        priced_cards += quantity
        if latest_date is None or price_point["date"] > latest_date:
            latest_date = price_point["date"]

    return {
        "total_eur": float(total),
        "priced_cards": priced_cards,
        "missing_cards": missing_cards,
        "latest_date": latest_date,
        "complete": missing_cards == 0,
    }


def latest_cardmarket_price(entry: dict[str, Any], finish: str) -> dict[str, Any] | None:
    mtgjson_finish = "normal" if finish == "nonfoil" else finish
    prices = (((entry.get("paper") or {}).get("cardmarket") or {}).get("retail") or {}).get(mtgjson_finish) or {}
    if not prices:
        return None
    latest_date = max(prices)
    return {"date": latest_date, "price": prices[latest_date]}


def missing_deck_line(deck_card: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "scryfall_id": deck_card["scryfall_id"],
        "name": deck_card["name"],
        "quantity": deck_card["quantity"],
        "finish": deck_card["finish"],
        "set_code": deck_card["set_code"],
        "collector_number": deck_card["collector_number"],
        "reason": reason,
    }


def deck_history(deck_cards: list[dict[str, Any]], mtgjson_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    point_maps: dict[tuple[str, str], dict[str, Decimal]] = {}
    for point in mtgjson_points:
        if point.get("source") != "mtgjson-cardmarket" or point.get("currency") != "EUR":
            continue
        key = (point["scryfall_id"], point["finish"])
        point_maps.setdefault(key, {})[point["snapshot_date"]] = Decimal(str(point["price"]))

    all_dates = sorted({date for point_map in point_maps.values() for date in point_map})
    history: list[dict[str, Any]] = []
    for snapshot_date in all_dates:
        total = Decimal("0")
        priced_cards = 0
        missing_cards = 0
        for deck_card in deck_cards:
            quantity = int(deck_card["quantity"])
            price = point_maps.get((deck_card["scryfall_id"], deck_card["finish"]), {}).get(snapshot_date)
            if price is None:
                missing_cards += quantity
            else:
                total += price * quantity
                priced_cards += quantity
        history.append(
            {
                "snapshot_date": snapshot_date,
                "total_eur": float(total),
                "priced_cards": priced_cards,
                "missing_cards": missing_cards,
            }
        )
    return history


def start_preload_job(limit: int | None = None) -> bool:
    with PRELOAD_LOCK:
        if PRELOAD_STATUS["running"]:
            return False
        PRELOAD_STATUS.update(
            {
                "running": True,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "finished_at": None,
                "error": None,
                "decks_total": 0,
                "decks_processed": 0,
                "unique_uuids": 0,
                "cached_uuids": 0,
                "fetched_uuids": 0,
                "missing_uuids": 0,
                "scryfall_cards_cached": 0,
                "points": 0,
                "snapshots_written": 0,
            }
        )

    thread = threading.Thread(target=preload_commander_prices, kwargs={"limit": limit}, daemon=True)
    thread.start()
    return True


def preload_status() -> dict[str, Any]:
    with PRELOAD_LOCK:
        return dict(PRELOAD_STATUS)


def update_preload_status(**updates: Any) -> None:
    with PRELOAD_LOCK:
        PRELOAD_STATUS.update(updates)


def preload_commander_prices(limit: int | None = None) -> None:
    try:
        decks = search_decks("", limit=limit or 10000, commander_only=True)
        if limit is not None:
            decks = decks[:limit]
        update_preload_status(decks_total=len(decks))

        deck_cards: list[dict[str, Any]] = []
        for index, deck in enumerate(decks, start=1):
            deck_payload = fetch_deck(deck["file_name"])
            deck_cards.extend(importable_deck_cards(deck_payload))
            update_preload_status(decks_processed=index)

        unique_by_uuid = {
            card["mtgjson_uuid"]: card
            for card in deck_cards
            if card.get("mtgjson_uuid") and card.get("scryfall_id")
        }
        update_preload_status(unique_uuids=len(unique_by_uuid))

        entries: dict[str, dict[str, Any]] = {}
        missing_uuids: list[str] = []
        with open_db() as conn:
            for uuid, deck_card in unique_by_uuid.items():
                save_mtgjson_uuid(
                    conn,
                    scryfall_id=deck_card["scryfall_id"],
                    mtgjson_uuid=uuid,
                    set_code=deck_card["set_code"],
                    collector_number=deck_card["collector_number"],
                )
                cached = cached_mtgjson_price_entry(conn, uuid)
                if cached is None:
                    missing_uuids.append(uuid)
                else:
                    entries[uuid] = cached
            conn.commit()

        update_preload_status(cached_uuids=len(entries))
        fetched_entries = extract_price_entries(missing_uuids)
        update_preload_status(fetched_uuids=len(fetched_entries), missing_uuids=len(set(missing_uuids) - set(fetched_entries)))

        all_points: list[dict[str, Any]] = []
        with open_db() as conn:
            scryfall_ids = sorted({card["scryfall_id"] for card in unique_by_uuid.values()})
            client = ScryfallClient()
            for index in range(0, len(scryfall_ids), 75):
                save_cards(conn, client.collection(scryfall_ids[index : index + 75]))
                update_preload_status(scryfall_cards_cached=min(index + 75, len(scryfall_ids)))

            for uuid, entry in fetched_entries.items():
                save_mtgjson_price_entry(conn, uuid, entry)
                entries[uuid] = entry

            for uuid, deck_card in unique_by_uuid.items():
                entry = entries.get(uuid)
                if entry is None:
                    continue
                all_points.extend(normalize_price_points(deck_card["scryfall_id"], entry))

            snapshots_written = save_external_price_snapshots(conn, all_points)
            conn.commit()

        update_preload_status(
            points=len(all_points),
            snapshots_written=snapshots_written,
            running=False,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    except Exception as error:  # noqa: BLE001 - background status should capture any failure.
        update_preload_status(
            running=False,
            error=str(error),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


def card_details(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": card.get("name"),
        "printed_name": card.get("printed_name"),
        "mana_cost": card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "type_line": card.get("type_line"),
        "printed_type_line": card.get("printed_type_line"),
        "oracle_text": card.get("oracle_text"),
        "printed_text": card.get("printed_text"),
        "flavor_text": card.get("flavor_text"),
        "power": card.get("power"),
        "toughness": card.get("toughness"),
        "loyalty": card.get("loyalty"),
        "defense": card.get("defense"),
        "colors": card.get("colors") or [],
        "color_identity": card.get("color_identity") or [],
        "keywords": card.get("keywords") or [],
        "legalities": card.get("legalities") or {},
        "artist": card.get("artist"),
        "released_at": card.get("released_at"),
        "layout": card.get("layout"),
        "rarity": card.get("rarity"),
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "purchase_uris": card.get("purchase_uris") or {},
        "related_uris": card.get("related_uris") or {},
        "card_faces": [card_face_details(face) for face in card.get("card_faces") or []],
    }


def card_face_details(face: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": face.get("name"),
        "mana_cost": face.get("mana_cost"),
        "type_line": face.get("type_line"),
        "oracle_text": face.get("oracle_text"),
        "printed_name": face.get("printed_name"),
        "printed_type_line": face.get("printed_type_line"),
        "printed_text": face.get("printed_text"),
        "flavor_text": face.get("flavor_text"),
        "power": face.get("power"),
        "toughness": face.get("toughness"),
        "loyalty": face.get("loyalty"),
        "defense": face.get("defense"),
        "artist": face.get("artist"),
    }


def rulings_to_json(rulings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "published_at": ruling.get("published_at"),
            "source": ruling.get("source"),
            "comment": ruling.get("comment"),
        }
        for ruling in rulings
    ]


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    with open_db():
        pass
    server = ThreadingHTTPServer((host, port), MvpRequestHandler)
    print(f"MTG PWA disponible sur http://{host}:{port}")
    print("Ctrl+C pour arreter le serveur.")
    server.serve_forever()
