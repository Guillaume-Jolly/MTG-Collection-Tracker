from __future__ import annotations

import json
import math
import mimetypes
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from .database import (
    DEFAULT_DB_PATH,
    CARDMARKET_GUIDE_SOURCE,
    add_collection_item,
    adjust_collection_quantity,
    batch_cardmarket_latest_guide,
    cardmarket_guide_bulk_history_points,
    cardmarket_guide_period_bounds,
    cardmarket_guide_pre_period_stats,
    cardmarket_latest_guide_for_card,
    cardmarket_guide_multi_series,
    cardmarket_mapping_stats,
    cardmarket_product_id_by_scryfall,
    cardmarket_product_insights,
    resolve_cardmarket_scryfall_id,
    card_summary,
    catalog_table,
    cached_mtgjson_price_entry,
    cached_mtgjson_uuid,
    collection_card_ids,
    collection_quantities_for_card,
    connect,
    delete_collection_item,
    display_price_for,
    get_cached_card,
    init_db,
    latest_snapshot,
    resolve_display_card_db,
    resolve_display_card_id,
    utc_now,
    VALID_DISPLAY_LANG_MODES,
    list_collection,
    oracle_collection_summary,
    collection_summary as db_collection_summary,
    set_deck_owned as db_set_deck_owned,
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
    deck_file_in_catalog,
    deck_thumbnail_info,
    deck_owned_status,
    extract_price_entry,
    extract_price_entries,
    fetch_deck,
    importable_deck_cards,
    list_deck_extensions,
    market_summaries,
    mtgjson_uuid_for_scryfall_card,
    normalize_price_points,
    search_decks,
)
from .local_cache import CacheError, catalog_image_url, ensure_set_icon, image_path
from .scryfall import ScryfallClient, ScryfallError
from .version import app_version_label, sync_build_info, version_identity
from .price_archive import archive_daily_prices
from .cardmarket_export import build_cardmarket_order_plan, cardmarket_product_url
from .price_sync import mtgjson_snapshots_need_sync
from .prices import FINISH_ORDER, PricePoint, available_finishes_for_card, chart_price_source, current_eur_price
from .sets_catalog import (
    COLLECTION_CATALOG_VERSION,
    MY_COLLECTION_PAGE_SIZES,
    blocks_catalog,
    enrich_blocks_with_collection,
    enrich_sections_with_stats,
    invalidate_owned_collection_cache,
    set_cards,
    list_owned_collection_cards,
    owned_scryfall_ids,
    scryfall_ids_for_set_block,
    scryfall_ids_for_set_code,
    set_sections,
    catalog_locations_for_set,
    market_eligible_set_codes,
    MARKET_MIN_RELEASE_DATE,
    set_age_years,
)


VALID_FINISHES = {"nonfoil", "foil", "etched"}
VALID_CONDITIONS = {"mint", "near_mint", "excellent", "good", "played", "poor"}
COLLECTION_RESERVED_SEGMENTS = frozenset({"owned", "blocks", "summary", "adjust", "refresh-prices"})
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
ARCHIVE_STATUS: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "message": None,
    "started_at": None,
    "finished_at": None,
    "last_archive_date": None,
    "last_archive_finished_at": None,
    "error": None,
    "skipped": False,
    "uuids_total": 0,
    "uuids_found": 0,
    "cards_processed": 0,
    "cards_total": 0,
    "snapshots_written": 0,
    "cardmarket_phase": "idle",
    "cardmarket_skipped": False,
    "cardmarket_rows_written": 0,
    "cardmarket_products_tracked": 0,
    "last_cardmarket_archive_date": None,
    "last_cardmarket_archive_finished_at": None,
}
ARCHIVE_LOCK = threading.Lock()
WEEKLY_BACKUP_STATUS: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "message": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "skipped": False,
    "rows_incremental": 0,
    "rows_snapshot": 0,
    "backup_size_gb": None,
}
WEEKLY_BACKUP_LOCK = threading.Lock()
STARTUP_STATUS: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "message": None,
    "progress": 0,
    "started_at": None,
    "finished_at": None,
    "skipped": False,
    "error": None,
    "catalog_categories": 0,
    "owned_cards_total": 0,
    "owned_cards_refreshed": 0,
    "snapshots_written": 0,
    "siblings_fetched": 0,
    "decks_indexed": 0,
    "market_tracked_cards": 0,
    "market_ranges_warmed": 0,
}
STARTUP_LOCK = threading.Lock()
COLLECTION_BLOCKS_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}
COLLECTION_BLOCKS_CACHE_TTL = 120.0


def invalidate_collection_blocks_cache(
    *,
    scryfall_ids: set[str] | None = None,
    full_rebuild: bool = False,
    skip_index: bool = False,
    schedule_sync: bool = True,
) -> None:
    COLLECTION_BLOCKS_CACHE["expires_at"] = 0.0
    COLLECTION_BLOCKS_CACHE["payload"] = None
    invalidate_owned_collection_cache()
    invalidate_collection_history_cache()
    if skip_index:
        return
    try:
        conn = connect()
        init_db(conn)
        from .collection_index import invalidate_collection_owned_index, schedule_collection_index_sync

        invalidate_collection_owned_index(
            conn,
            scryfall_ids=scryfall_ids,
            full_rebuild=full_rebuild,
        )
        conn.commit()
        conn.close()
        if schedule_sync and not full_rebuild:
            schedule_collection_index_sync()
    except Exception:  # noqa: BLE001 - cache invalidation should not break writes.
        pass


def order_plan_items_for_set(
    conn,
    set_code: str,
    *,
    finish: str,
    only_missing: bool,
) -> list[dict[str, Any]]:
    payload = set_cards(set_code)
    return _order_plan_items_from_catalog(payload, finish=finish, only_missing=only_missing)


def order_plan_items_for_section(
    conn,
    section_code: str,
    *,
    finish: str,
    only_missing: bool,
) -> list[dict[str, Any]]:
    payload = set_cards(section_code)
    return _order_plan_items_from_catalog(payload, finish=finish, only_missing=only_missing)


def order_plan_items_from_lines(
    conn,
    lines: list[dict[str, Any]],
    *,
    default_finish: str,
    only_missing: bool,
) -> list[dict[str, Any]]:
    if not lines:
        return []
    scryfall_ids = [str(line.get("scryfall_id") or "").strip() for line in lines]
    scryfall_ids = [card_id for card_id in scryfall_ids if card_id]
    if not scryfall_ids:
        return []
    cards_table = catalog_table("cards")
    placeholders = ",".join("?" for _ in scryfall_ids)
    rows = conn.execute(
        f"""
        SELECT scryfall_id, name, printed_name, set_code, set_name, raw_json
        FROM {cards_table}
        WHERE scryfall_id IN ({placeholders})
        """,
        scryfall_ids,
    ).fetchall()
    row_by_id = {row["scryfall_id"]: row for row in rows}
    owned_ids = set(collection_card_ids(conn)) if only_missing else set()
    items: list[dict[str, Any]] = []
    for line in lines:
        scryfall_id = str(line.get("scryfall_id") or "").strip()
        if not scryfall_id:
            continue
        if only_missing and scryfall_id in owned_ids:
            continue
        row = row_by_id.get(scryfall_id)
        if row is None:
            continue
        card = json.loads(row["raw_json"])
        item_finish = str(line.get("finish") or default_finish).strip().lower()
        if item_finish not in VALID_FINISHES:
            item_finish = default_finish
        items.append(
            {
                "scryfall_id": scryfall_id,
                "name": row["printed_name"] or row["name"] or card.get("name") or "",
                "printed_name": row["printed_name"],
                "set_name": row["set_name"] or row["set_code"] or card.get("set_name") or "",
                "set_code": row["set_code"] or card.get("set") or "",
                "quantity": max(1, int(line.get("quantity") or 1)),
                "finish": item_finish,
            }
        )
    return items


def order_plan_items_for_ids(
    conn,
    scryfall_ids: list[str],
    *,
    finish: str,
    only_missing: bool,
) -> list[dict[str, Any]]:
    cards_table = catalog_table("cards")
    placeholders = ",".join("?" for _ in scryfall_ids)
    rows = conn.execute(
        f"""
        SELECT scryfall_id, name, printed_name, set_code, set_name, raw_json
        FROM {cards_table}
        WHERE scryfall_id IN ({placeholders})
        """,
        scryfall_ids,
    ).fetchall()
    owned_ids = set(collection_card_ids(conn)) if only_missing else set()
    items: list[dict[str, Any]] = []
    for row in rows:
        if only_missing and row["scryfall_id"] in owned_ids:
            continue
        card = json.loads(row["raw_json"])
        items.append(
            {
                "scryfall_id": row["scryfall_id"],
                "name": row["printed_name"] or row["name"] or card.get("name") or "",
                "printed_name": row["printed_name"],
                "set_name": row["set_name"] or row["set_code"] or card.get("set_name") or "",
                "set_code": row["set_code"] or card.get("set") or "",
                "quantity": 1,
                "finish": finish,
            }
        )
    return items


def _order_plan_items_from_catalog(
    payload: dict[str, Any],
    *,
    finish: str,
    only_missing: bool,
) -> list[dict[str, Any]]:
    set_name = payload.get("set_name") or payload.get("set_code") or ""
    items: list[dict[str, Any]] = []
    for card in payload.get("cards") or []:
        scryfall_id = card.get("scryfall_id")
        if not scryfall_id:
            continue
        if only_missing and card.get("owned"):
            continue
        items.append(
            {
                "scryfall_id": scryfall_id,
                "name": card.get("printed_name") or card.get("name") or "",
                "set_name": card.get("set_name") or set_name,
                "set_code": card.get("set_code") or payload.get("set_code") or "",
                "quantity": 1,
                "finish": finish,
            }
        )
    return items


class MvpRequestHandler(BaseHTTPRequestHandler):
    server_version = "MTGPWA/0.1"
    static_dir = Path(__file__).parent / "static"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parse_qs(parsed.query))
            return
        if parsed.path.startswith("/cache/images/"):
            self.serve_cached_image(parsed.path)
            return
        if parsed.path.startswith("/cache/set-icons/"):
            self.serve_set_icon(parsed.path)
            return
        if parsed.path == "/version.js":
            self.serve_version_js()
            return
        if parsed.path == "/build-info.json":
            self.serve_build_info()
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
            path = path.rstrip("/") or "/"
            if method == "GET" and path == "/api/health":
                self.health()
                return
            if method == "GET" and path == "/api/db/audit":
                self.db_audit()
                return
            if method == "GET" and path == "/api/db/backup-status":
                self.db_backup_status()
                return
            if method == "POST" and path == "/api/db/backup-run":
                self.db_backup_run()
                return
            if method == "GET" and path == "/api/search":
                self.search_cards(query)
                return
            if method == "GET" and path == "/api/collection/summary":
                self.collection_summary()
                return
            if method == "GET" and path == "/api/my-collection":
                self.collection_owned(query)
                return
            if method == "GET" and path == "/api/my-collection/history":
                self.collection_owned_history(query)
                return
            if method == "GET" and path == "/api/my-collection/index-status":
                from .collection_index import index_rebuild_status

                self.json_response(index_rebuild_status())
                return
            if method == "GET" and path == "/api/my-collection/portfolio":
                self.collection_portfolio()
                return
            if method == "GET" and path == "/api/my-collection/issues":
                self.collection_issues()
                return
            if method == "GET" and path == "/api/my-collection/export":
                self.collection_export()
                return
            if method == "POST" and path == "/api/my-collection/import":
                self.collection_import()
                return
            if method == "GET" and path == "/api/wishlist":
                self.wishlist_list()
                return
            if method == "POST" and path == "/api/wishlist":
                self.wishlist_upsert()
                return
            if method == "DELETE" and path.startswith("/api/wishlist/"):
                item_id = int(path.rsplit("/", 1)[-1])
                self.wishlist_delete(item_id)
                return
            if method == "GET" and path == "/api/price-alerts":
                self.price_alerts_list()
                return
            if method == "POST" and path == "/api/price-alerts":
                self.price_alert_create()
                return
            if method == "DELETE" and path.startswith("/api/price-alerts/"):
                alert_id = int(path.rsplit("/", 1)[-1])
                self.price_alert_delete(alert_id)
                return
            if method == "GET" and path == "/api/cardmarket/archive-status":
                self.cardmarket_archive_status()
                return
            if method == "GET" and path.startswith("/api/collection/missing/"):
                set_code = path.rsplit("/", 1)[-1]
                self.collection_missing(set_code, query)
                return
            if method == "GET" and path.startswith("/api/oracle/"):
                oracle_id = path.removeprefix("/api/oracle/").strip("/")
                self.oracle_collection(oracle_id)
                return
            if method == "GET" and path == "/api/binder":
                self.binder_list(query)
                return
            if method == "POST" and path == "/api/binder":
                self.binder_upsert()
                return
            if method == "DELETE" and path.startswith("/api/binder/"):
                slot_id = int(path.rsplit("/", 1)[-1])
                self.binder_delete(slot_id)
                return
            if method == "POST" and path == "/api/trade/export":
                self.trade_export()
                return
            if method == "POST" and path == "/api/trade/summary":
                self.trade_summary()
                return
            if method == "POST" and path == "/api/trade/import-match":
                self.trade_import_match()
                return
            if method == "GET" and path == "/api/price-alerts/history":
                self.price_alerts_history()
                return
            if method == "POST" and path.startswith("/api/price-alerts/") and path.endswith("/reactivate"):
                alert_id = int(path.removeprefix("/api/price-alerts/").removesuffix("/reactivate"))
                self.price_alert_reactivate(alert_id)
                return
            if method == "POST" and path == "/api/wishlist/alert":
                self.wishlist_create_alert()
                return
            if method == "GET" and path == "/api/binder/names":
                self.binder_names()
                return
            if method == "POST" and path == "/api/my-collection/merge-duplicate":
                self.merge_collection_duplicate()
                return
            if method == "GET" and path == "/api/backup/export":
                self.export_backup()
                return
            if method == "POST" and path == "/api/price-alerts/check":
                self.price_alerts_check()
                return
            if method == "GET" and path == "/api/market/movers":
                self.market_movers(query)
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
            if method == "GET" and path == "/api/decks/extensions":
                self.deck_extensions(query)
                return
            if method == "POST" and path == "/api/decks/import":
                self.import_deck()
                return
            if method == "POST" and path == "/api/decks/remove":
                self.remove_deck_from_collection()
                return
            if method == "POST" and path == "/api/decks/owned":
                self.set_deck_owned()
                return
            if method == "GET" and path == "/api/decks/detail":
                self.deck_detail(query)
                return
            if method == "GET" and path == "/api/decks/history":
                self.deck_history_detail(query)
                return
            if method == "POST" and path == "/api/preload/commander-prices":
                self.start_commander_preload()
                return
            if method == "GET" and path == "/api/preload/commander-prices":
                self.commander_preload_status()
                return
            if method == "POST" and path == "/api/prices/archive":
                self.start_price_archive()
                return
            if method == "GET" and path == "/api/prices/archive":
                self.price_archive_status()
                return
            if method == "POST" and path == "/api/startup/warmup":
                self.start_startup_warmup()
                return
            if method == "GET" and path == "/api/startup/status":
                self.startup_warmup_status()
                return

            if method == "GET" and path == "/api/collection/blocks":
                self.collection_blocks()
                return
            if method == "GET" and path == "/api/collection/owned":
                self.collection_owned(query)
                return
            if method == "GET" and path.startswith("/api/set-icons/"):
                slug = path.removeprefix("/api/set-icons/").removesuffix(".svg").strip()
                if slug:
                    self.serve_set_icon_slug(slug)
                    return
                raise ValueError("Identifiant d'icone invalide.")
            if method == "POST" and path == "/api/collection/adjust":
                self.adjust_collection()
                return
            if method == "POST" and path == "/api/collection/refresh-prices":
                self.refresh_collection_prices()
                return

            if method == "POST" and path == "/api/cardmarket/order-plan":
                self.cardmarket_order_plan()
                return

            segments = path.strip("/").split("/")
            if (
                method == "GET"
                and len(segments) == 4
                and segments[:2] == ["api", "collection"]
                and segments[3] == "cards"
            ):
                self.collection_set_cards(segments[2], query)
                return
            if len(segments) == 3 and segments[:2] == ["api", "collection"]:
                segment = segments[2].lower()
                if method == "GET" and segment == "owned":
                    self.collection_owned(query)
                    return
                if method == "POST" and segment == "refresh-prices":
                    self.refresh_collection_prices()
                    return
                if method == "POST" and segment == "adjust":
                    self.adjust_collection()
                    return
                if method == "GET" and not segment.isdigit() and segment not in COLLECTION_RESERVED_SEGMENTS:
                    self.collection_set_detail(segments[2])
                    return
                if segment.isdigit():
                    item_id = int(segment)
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

            if len(segments) == 3 and segments[:2] == ["api", "decks"] and method == "POST":
                if segments[2] == "owned":
                    self.set_deck_owned()
                    return
                if segments[2] == "import":
                    self.import_deck()
                    return
                if segments[2] == "remove":
                    self.remove_deck_from_collection()
                    return

            self.json_response({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.json_response({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
        except ScryfallError as error:
            self.json_response({"error": str(error)}, status=HTTPStatus.BAD_GATEWAY)
        except CacheError as error:
            self.json_response({"error": str(error)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as error:  # noqa: BLE001 - server should return JSON errors.
            try:
                self.json_response({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except (ConnectionAbortedError, BrokenPipeError):
                return

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
        display_lang = parse_display_lang(query)
        with open_db() as conn:
            save_cards(conn, cards)
            conn.commit()
            response = []
            for card in cards:
                display_card = resolve_display_card_db(conn, card, display_lang)
                response.append(card_summary(conn, display_card, finish))
        self.json_response({"cards": response, "display_lang": display_lang})

    def collection(self) -> None:
        with open_db() as conn:
            self.json_response(list_collection(conn))

    def health(self) -> None:
        from .db_audit import collect_db_audit
        from .weekly_backup import weekly_backup_status

        audit = collect_db_audit()
        backup_status = weekly_backup_status()
        self.json_response(
            {
                "status": "ok",
                "api_version": 3,
                "app_version": app_version_label(),
                **version_identity(),
                "features": ["market", "startup", "db_audit"],
                "db": {
                    "overall_status": audit["overall_status"],
                    "main_db_gb": audit["db_files"].get("main", {}).get("size_gb"),
                    "backup_gb": audit["backup"].get("size_gb"),
                    "backup_due": backup_status.get("due"),
                    "warnings": audit.get("warnings") or [],
                },
            }
        )

    def db_audit(self) -> None:
        from .db_audit import collect_db_audit

        self.json_response(collect_db_audit())

    def db_backup_status(self) -> None:
        from .weekly_backup import weekly_backup_status

        self.json_response(weekly_backup_status())

    def db_backup_run(self) -> None:
        payload = self.read_json(default={})
        force = bool(payload.get("force"))
        started = start_weekly_backup_job(force=force)
        self.json_response({"started": started, "status": weekly_backup_status_payload()})

    def collection_summary(self) -> None:
        with open_db() as conn:
            from .collection_index import collection_index_is_ready, get_cached_collection_summary

            cached = get_cached_collection_summary(conn, "fr") if collection_index_is_ready(conn, "fr") else None
            if cached:
                payload = db_collection_summary(conn)
                summary = payload.get("summary") or {}
                summary["unique_cards"] = cached["unique_lines"]
                summary["total_cards"] = cached["total_cards"]
                summary["estimated_value_eur"] = cached["total_value_eur"]
                summary["from_index_cache"] = True
                self.json_response({"summary": summary})
                return
            self.json_response(db_collection_summary(conn))

    def collection_blocks(self) -> None:
        now = time.time()
        cached = COLLECTION_BLOCKS_CACHE
        if cached["payload"] is not None and now < cached["expires_at"]:
            self.json_response(
                {**cached["payload"], "catalog_version": COLLECTION_CATALOG_VERSION},
                extra_headers={"Cache-Control": "no-store"},
            )
            return

        payload = {"categories": enrich_blocks_with_collection(blocks_catalog())}
        cached["payload"] = payload
        cached["expires_at"] = now + COLLECTION_BLOCKS_CACHE_TTL
        self.json_response(
            {
                **payload,
                "catalog_version": COLLECTION_CATALOG_VERSION,
            },
            extra_headers={"Cache-Control": "no-store"},
        )

    def collection_set_detail(self, set_code: str) -> None:
        payload = set_sections(set_code)
        payload["sections"] = enrich_sections_with_stats(payload["sections"])
        self.json_response(payload)

    def collection_set_cards(self, set_code: str, query: dict[str, list[str]]) -> None:
        sort = one(query, "sort", "price_desc")
        display_lang = parse_display_lang(query)
        self.json_response(set_cards(set_code, sort=sort, display_lang=display_lang))

    def cardmarket_order_plan(self) -> None:
        body = self.read_json(default={})
        set_code = str(body.get("set_code") or "").strip().upper()
        section_code = str(body.get("section_code") or "").strip().upper()
        finish = str(body.get("finish") or "nonfoil").strip().lower()
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")
        scryfall_ids = [str(card_id).strip() for card_id in (body.get("scryfall_ids") or []) if str(card_id).strip()]
        deck_lines = body.get("lines") or []
        only_missing = bool(body.get("only_missing"))
        playset = bool(body.get("playset"))
        display_lang = str(body.get("display_lang") or "merge").strip().lower()
        shipping_profile = str(body.get("shipping_profile") or "letter").strip().lower()
        use_wishlist = bool(body.get("from_wishlist"))
        with open_db() as conn:
            if use_wishlist:
                from .collection_extras import list_wishlist

                wishlist_items = list_wishlist(conn)
                deck_lines = [
                    {
                        "scryfall_id": item["scryfall_id"],
                        "finish": item.get("finish") or finish,
                        "quantity": item.get("quantity") or 1,
                    }
                    for item in wishlist_items
                    if item.get("scryfall_id")
                ]
                items = order_plan_items_from_lines(
                    conn,
                    deck_lines,
                    default_finish=finish,
                    only_missing=only_missing,
                )
            elif deck_lines:
                items = order_plan_items_from_lines(
                    conn,
                    deck_lines,
                    default_finish=finish,
                    only_missing=only_missing,
                )
            elif scryfall_ids:
                items = order_plan_items_for_ids(conn, scryfall_ids, finish=finish, only_missing=only_missing)
            elif section_code:
                items = order_plan_items_for_section(conn, section_code, finish=finish, only_missing=only_missing)
            elif set_code:
                items = order_plan_items_for_set(conn, set_code, finish=finish, only_missing=only_missing)
            else:
                raise ValueError("Precisez set_code, section_code, scryfall_ids, lines ou from_wishlist.")
            self.json_response(
                build_cardmarket_order_plan(
                    conn,
                    items,
                    finish=finish,
                    playset=playset,
                    display_lang=display_lang,
                    shipping_profile=shipping_profile,
                )
            )

    def collection_owned(self, query: dict[str, list[str]]) -> None:
        from .collection_index import index_rebuild_status, parse_my_collection_filters

        sort = one(query, "sort", "name_asc")
        display_lang = parse_display_lang(query)
        page_size, offset = parse_my_collection_page(query)
        filters = parse_my_collection_filters(query)
        with open_db() as conn:
            self.json_response(
                {
                    **list_owned_collection_cards(
                        conn,
                        sort=sort,
                        display_lang=display_lang,
                        limit=page_size,
                        offset=offset,
                        filters=filters,
                    ),
                    "index_status": index_rebuild_status(),
                }
            )

    def collection_owned_history(self, query: dict[str, list[str]]) -> None:
        source_key = one(query, "source", "cardmarket")
        range_key = parse_history_range(query)
        options = parse_history_options(query)
        if options.history_mode == "archive" and one(query, "confirm_archive", "0") not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            with open_db() as conn:
                from .collection_extras import cardmarket_archive_status

                archive_meta = cardmarket_archive_status(conn)
                if archive_meta["archive_days"] < 7:
                    self.json_response(
                        {
                            "requires_confirmation": True,
                            "history_mode": "archive",
                            "archive_meta": archive_meta,
                            "message": (
                                "L'archive CM est courte : le calcul complet peut prendre plusieurs minutes. "
                                "Confirmez avec confirm_archive=1 ou utilisez history_mode=fast."
                            ),
                        }
                    )
                    return
        cached = get_cached_collection_history(source_key, options, range_key)
        if cached is not None:
            self.json_response(cached)
            return
        with open_db() as conn:
            payload = collection_valuation_history(conn, source_key, options, range_key=range_key)
            cache_collection_history(source_key, options, range_key, payload)
            self.json_response(payload)

    def collection_portfolio(self) -> None:
        from .collection_extras import portfolio_stats

        with open_db() as conn:
            self.json_response(portfolio_stats(conn))

    def collection_issues(self) -> None:
        from .collection_extras import collection_issues as detect_collection_issues

        with open_db() as conn:
            self.json_response(detect_collection_issues(conn))

    def collection_export(self) -> None:
        from .collection_extras import export_collection_csv

        with open_db() as conn:
            csv_text = export_collection_csv(conn)
        data = csv_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="ma-collection.csv"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError):
            return

    def collection_import(self) -> None:
        from .collection_extras import import_collection_csv

        payload = self.read_json()
        raw_text = str(payload.get("csv") or "")
        if not raw_text.strip():
            raise ValueError("Le champ csv est requis.")
        with open_db() as conn:
            result = import_collection_csv(conn, raw_text)
        invalidate_collection_blocks_cache(full_rebuild=True)
        self.json_response(result)

    def wishlist_list(self) -> None:
        from .collection_extras import list_wishlist

        with open_db() as conn:
            self.json_response({"items": list_wishlist(conn)})

    def wishlist_upsert(self) -> None:
        from .collection_extras import upsert_wishlist_item

        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        with open_db() as conn:
            item = upsert_wishlist_item(
                conn,
                scryfall_id=scryfall_id,
                finish=str(payload.get("finish") or "nonfoil"),
                quantity=int(payload.get("quantity") or 1),
                priority=int(payload.get("priority") or 0),
                max_price_eur=payload.get("max_price_eur"),
                notes=payload.get("notes"),
                auto_alert=bool(payload.get("auto_alert")),
            )
        self.json_response(item)

    def wishlist_delete(self, item_id: int) -> None:
        from .collection_extras import delete_wishlist_item

        with open_db() as conn:
            delete_wishlist_item(conn, item_id)
        self.json_response({"deleted": item_id})

    def price_alerts_list(self) -> None:
        from .collection_extras import list_price_alerts

        with open_db() as conn:
            self.json_response({"alerts": list_price_alerts(conn)})

    def price_alert_create(self) -> None:
        from .collection_extras import create_price_alert

        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        with open_db() as conn:
            alert = create_price_alert(
                conn,
                scryfall_id=scryfall_id,
                finish=str(payload.get("finish") or "nonfoil"),
                direction=str(payload.get("direction") or "below"),
                threshold_eur=float(payload.get("threshold_eur") or 0),
                source=str(payload.get("source") or "cardmarket"),
            )
        self.json_response(alert)

    def price_alert_delete(self, alert_id: int) -> None:
        from .collection_extras import delete_price_alert

        with open_db() as conn:
            delete_price_alert(conn, alert_id)
        self.json_response({"deleted": alert_id})

    def price_alerts_history(self) -> None:
        from .collection_extras import list_price_alert_events

        with open_db() as conn:
            self.json_response({"events": list_price_alert_events(conn)})

    def price_alert_reactivate(self, alert_id: int) -> None:
        from .collection_extras import reactivate_price_alert

        with open_db() as conn:
            ok = reactivate_price_alert(conn, alert_id)
        if not ok:
            self.json_response({"error": "Alerte introuvable"}, status=HTTPStatus.NOT_FOUND)
            return
        self.json_response({"reactivated": alert_id})

    def wishlist_create_alert(self) -> None:
        from .collection_extras import create_wishlist_price_alert

        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        finish = str(payload.get("finish") or "nonfoil")
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        with open_db() as conn:
            alert = create_wishlist_price_alert(conn, scryfall_id=scryfall_id, finish=finish)
        if alert is None:
            raise ValueError("Pas de max_price sur cette ligne wishlist.")
        self.json_response(alert)

    def binder_names(self) -> None:
        from .collection_extras import list_binder_names

        with open_db() as conn:
            self.json_response({"names": list_binder_names(conn)})

    def merge_collection_duplicate(self) -> None:
        from .collection_extras import merge_duplicate_collection_rows
        from .collection_index import schedule_collection_index_sync

        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        finish = str(payload.get("finish") or "nonfoil")
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        with open_db() as conn:
            result = merge_duplicate_collection_rows(conn, scryfall_id, finish)
        invalidate_collection_blocks_cache(scryfall_ids={scryfall_id})
        schedule_collection_index_sync()
        self.json_response(result)

    def export_backup(self) -> None:
        from .collection_extras import export_app_backup

        with open_db() as conn:
            self.json_response(export_app_backup(conn))

    def cardmarket_archive_status(self) -> None:
        from .collection_extras import cardmarket_archive_status as archive_status

        with open_db() as conn:
            self.json_response(archive_status(conn))

    def collection_missing(self, set_code: str, query: dict[str, list[str]]) -> None:
        from .collection_extras import missing_cards_for_set

        display_lang = parse_display_lang(query)
        with open_db() as conn:
            self.json_response(missing_cards_for_set(conn, set_code, display_lang=display_lang))

    def oracle_collection(self, oracle_id: str) -> None:
        from .collection_extras import oracle_collection_view

        with open_db() as conn:
            self.json_response(oracle_collection_view(conn, oracle_id))

    def binder_list(self, query: dict[str, list[str]]) -> None:
        from .collection_extras import list_binder_slots

        binder_name = one(query, "binder", "Principal")
        with open_db() as conn:
            self.json_response({"slots": list_binder_slots(conn, binder_name=binder_name)})

    def binder_upsert(self) -> None:
        from .collection_extras import upsert_binder_slot

        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        with open_db() as conn:
            slot = upsert_binder_slot(
                conn,
                scryfall_id=scryfall_id,
                finish=str(payload.get("finish") or "nonfoil"),
                binder_name=str(payload.get("binder_name") or "Principal"),
                page_number=int(payload.get("page_number") or 1),
                slot_number=int(payload.get("slot_number") or 1),
                condition=str(payload.get("condition") or "near_mint"),
                quantity=int(payload.get("quantity") or 1),
                notes=payload.get("notes"),
                slot_id=payload.get("id"),
            )
        self.json_response(slot)

    def binder_delete(self, slot_id: int) -> None:
        from .collection_extras import delete_binder_slot

        with open_db() as conn:
            delete_binder_slot(conn, slot_id)
        self.json_response({"deleted": slot_id})

    def trade_export(self) -> None:
        from .collection_extras import (
            enrich_trade_lines_with_prices,
            export_trade_csv,
            export_trade_hw_text,
            export_trade_mcm_decklist,
        )

        payload = self.read_json()
        format_key = str(payload.get("format") or "csv").strip().lower()
        have_lines = payload.get("have_lines") or []
        want_lines = payload.get("want_lines") or []
        lines = payload.get("lines") or []
        if not have_lines and not want_lines and not lines:
            raise ValueError("have_lines, want_lines ou lines est requis.")
        with open_db() as conn:
            if have_lines or want_lines:
                have_lines = enrich_trade_lines_with_prices(conn, have_lines)
                want_lines = enrich_trade_lines_with_prices(conn, want_lines)
            else:
                lines = enrich_trade_lines_with_prices(conn, lines)

        if format_key == "hw":
            text = export_trade_hw_text(have_lines or lines, want_lines)
            filename = "trade-hw.txt"
            content_type = "text/plain; charset=utf-8"
        elif format_key == "mcm":
            text = export_trade_mcm_decklist(want_lines or have_lines or lines)
            filename = "trade-mcm.txt"
            content_type = "text/plain; charset=utf-8"
        else:
            text = export_trade_csv(have_lines or lines)
            filename = "trade-list.csv"
            content_type = "text/csv; charset=utf-8"

        data = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError):
            return

    def trade_summary(self) -> None:
        from .collection_extras import enrich_trade_lines_with_prices, trade_lines_total_eur

        payload = self.read_json(default={})
        have_lines = payload.get("have_lines") or []
        want_lines = payload.get("want_lines") or []
        with open_db() as conn:
            have_lines = enrich_trade_lines_with_prices(conn, have_lines)
            want_lines = enrich_trade_lines_with_prices(conn, want_lines)
        have_total = trade_lines_total_eur(have_lines)
        want_total = trade_lines_total_eur(want_lines)
        delta = round(have_total - want_total, 2)
        equity_pct = None
        if want_total > 0:
            equity_pct = round((delta / want_total) * 100, 1)
        self.json_response(
            {
                "have_total_eur": have_total,
                "want_total_eur": want_total,
                "delta_eur": delta,
                "equity_pct": equity_pct,
                "currency": "EUR",
                "note": "Valeurs indicatives (trend Cardmarket / prix affiches).",
            }
        )

    def trade_import_match(self) -> None:
        from .collection_extras import match_trade_import

        payload = self.read_json(default={})
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text est requis.")
        with open_db() as conn:
            result = match_trade_import(conn, text)
        self.json_response(result)

    def price_alerts_check(self) -> None:
        from .collection_extras import check_price_alerts

        with open_db() as conn:
            triggered = check_price_alerts(conn)
        self.json_response({"triggered": triggered})

    def market_movers(self, query: dict[str, list[str]]) -> None:
        source_key = one(query, "source", "cardmarket")
        range_key = parse_history_range(query)
        options = parse_history_options(query)
        cached = get_cached_market_movers(source_key, options, range_key)
        if cached is not None:
            self.json_response(cached)
            return
        with open_db() as conn:
            payload = market_price_movers(conn, source_key, options, range_key=range_key)
            cache_market_movers(source_key, options, range_key, payload)
            self.json_response(payload)

    def adjust_collection(self) -> None:
        payload = self.read_json()
        scryfall_id = str(payload.get("scryfall_id") or "").strip()
        finish = str(payload.get("finish") or "nonfoil")
        delta = int(payload.get("delta") or 0)
        if not scryfall_id:
            raise ValueError("scryfall_id est requis.")
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")

        with open_db() as conn:
            client = ScryfallClient()
            card = refresh_card_from_scryfall(conn, client, scryfall_id)
            result = adjust_collection_quantity(conn, scryfall_id=scryfall_id, finish=finish, delta=delta)
            summary = db_collection_summary(conn)
        invalidate_collection_blocks_cache(scryfall_ids={scryfall_id})
        self.json_response({**summary, "adjust": result})

    def refresh_collection_prices(self) -> None:
        payload = self.read_json(default={})
        scope = str(payload.get("scope") or "section").strip()
        set_code = str(payload.get("set_code") or "").strip().upper()
        section_code = str(payload.get("section_code") or set_code).strip().upper()

        if scope == "owned":
            with open_db() as conn:
                scryfall_ids = owned_scryfall_ids(conn)
        else:
            if not set_code and not section_code:
                raise ValueError("set_code ou section_code est requis.")

            if scope == "block":
                scryfall_ids = scryfall_ids_for_set_block(set_code or section_code)
            else:
                scryfall_ids = scryfall_ids_for_set_code(section_code or set_code)

        if not scryfall_ids:
            raise ValueError("Aucune carte trouvee pour ce scope.")

        offset = max(0, int(payload.get("offset", 0)))
        batch_size = max(1, min(75, int(payload.get("limit", 75))))
        batch_ids = scryfall_ids[offset : offset + batch_size]
        if not batch_ids and offset == 0:
            raise ValueError("Aucune carte trouvee pour ce scope.")
        if not batch_ids:
            self.json_response(
                {
                    "refresh": {
                        "scope": scope,
                        "set_code": set_code or section_code,
                        "section_code": section_code or set_code,
                        "cards_total": len(scryfall_ids),
                        "offset": offset,
                        "next_offset": offset,
                        "done": True,
                        "cards_refreshed": 0,
                        "snapshots_written": 0,
                        "errors": 0,
                    }
                }
            )
            return

        client = ScryfallClient()
        refreshed = 0
        skipped = 0
        snapshot_count = 0
        errors = 0
        with open_db() as conn:
            from .price_sync import card_price_sync_plan

            stale_ids: list[str] = []
            mtgjson_only_ids: list[str] = []
            for scryfall_id in batch_ids:
                plan = card_price_sync_plan(conn, scryfall_id)
                if plan["skip"]:
                    skipped += 1
                    continue
                if plan["needs_scryfall"] or plan["needs_fallback"]:
                    stale_ids.append(scryfall_id)
                elif plan["needs_mtgjson"]:
                    mtgjson_only_ids.append(scryfall_id)

            try:
                if stale_ids:
                    cards = client.collection(stale_ids)
                    save_cards(conn, cards)
                    for card in cards:
                        snapshot_count += save_price_snapshots(conn, card)
                        for card_finish in available_finishes_for_card(card):
                            snapshot_count += ensure_price_fallback(conn, client, card, card_finish)
                        snapshot_count += sync_mtgjson_for_card(conn, card)
                    refreshed += len(cards)
                    client.throttle()
                for scryfall_id in mtgjson_only_ids:
                    card = get_cached_card(conn, scryfall_id)
                    if not card:
                        continue
                    snapshot_count += sync_mtgjson_for_card(conn, card)
                    refreshed += 1
            except ScryfallError:
                errors = len(stale_ids)
            conn.commit()

        next_offset = offset + len(batch_ids)
        done = next_offset >= len(scryfall_ids)

        if done:
            from .sets_catalog import refresh_set_stats_cache

            for code in {section_code or set_code, set_code}:
                if code:
                    refresh_set_stats_cache(code)
            invalidate_collection_blocks_cache(scryfall_ids=set(scryfall_ids))

        self.json_response(
            {
                "refresh": {
                    "scope": scope,
                    "set_code": set_code or section_code,
                    "section_code": section_code or set_code,
                    "cards_total": len(scryfall_ids),
                    "offset": offset,
                    "next_offset": next_offset,
                    "done": done,
                    "cards_refreshed": refreshed,
                    "cards_skipped": skipped,
                    "snapshots_written": snapshot_count,
                    "errors": errors,
                }
            }
        )

    def search_decks(self, query: dict[str, list[str]]) -> None:
        search = one(query, "q", "").strip()
        page = max(1, int(one(query, "page", "1")))
        page_size = max(1, min(50, int(one(query, "page_size", "20"))))
        offset = (page - 1) * page_size
        commander_only = one(query, "commander_only", "true").lower() in {"1", "true", "yes", "on"}
        hide_collector = one(query, "hide_collector", "false").lower() in {"1", "true", "yes", "on"}
        extension = one(query, "extension", "").strip()
        sort = one(query, "sort", "release_desc")
        decks, total = search_decks(
            search,
            limit=page_size,
            offset=offset,
            commander_only=commander_only,
            hide_collector=hide_collector,
            extension=extension,
            sort=sort,
        )
        with open_db() as conn:
            response_decks = []
            for deck in decks:
                deck_payload = fetch_deck(deck["file_name"])
                enriched = dict(deck)
                enriched["price_estimate"] = deck_menu_price_estimate(conn, deck_payload)
                enriched["thumbnail"] = deck_thumbnail_info(deck_payload)
                enriched.update(deck_owned_status(conn, deck["file_name"], deck_payload))
                response_decks.append(enriched)
        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        self.json_response(
            {
                "decks": response_decks,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        )

    def deck_extensions(self, query: dict[str, list[str]]) -> None:
        commander_only = one(query, "commander_only", "true").lower() in {"1", "true", "yes", "on"}
        hide_collector = one(query, "hide_collector", "false").lower() in {"1", "true", "yes", "on"}
        extensions = list_deck_extensions(commander_only=commander_only, hide_collector=hide_collector)
        self.json_response({"extensions": extensions})

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
            deck_owned = deck_owned_status(conn, file_name, deck)
            from .collection_extras import deck_cards_to_buy

            to_buy = deck_cards_to_buy(conn, deck_cards)

        self.json_response(
            {
                "deck": {**deck_summary(deck, file_name), **deck_owned},
                "commanders": commanders,
                "cards_by_section": grouped_cards,
                "valuation": valuation,
                "mtgjson": mtgjson_status,
                "to_buy": to_buy,
            }
        )

    def deck_history_detail(self, query: dict[str, list[str]]) -> None:
        file_name = one(query, "file_name", "").strip()
        if not file_name:
            raise ValueError("file_name est requis.")
        source_key = one(query, "source", "cardmarket")
        options = parse_history_options(query)
        deck = fetch_deck(file_name)
        deck_cards = importable_deck_cards(deck)
        with open_db() as conn:
            self.json_response(deck_valuation_history(conn, deck_cards, source_key, options))

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

            db_set_deck_owned(conn, file_name, True)
            response = list_collection(conn)
            response["deck_import"] = {
                "deck": {**deck_summary(deck, file_name), "owned": True, "owned_source": "manual"},
                "imported_cards": imported,
                "missing_cards": missing,
            }
        touched = {card["scryfall_id"] for card in deck_cards}
        invalidate_collection_blocks_cache(scryfall_ids=touched)
        self.json_response(response, status=HTTPStatus.CREATED)

    def remove_deck_from_collection(self) -> None:
        payload = self.read_json()
        file_name = str(payload.get("file_name") or "").strip()
        if not file_name:
            raise ValueError("file_name est requis.")

        deck = fetch_deck(file_name)
        deck_cards = importable_deck_cards(deck)
        if not deck_cards:
            raise ValueError("Aucune carte importable trouvee dans ce deck.")

        removed = 0
        touched_ids: set[str] = set()
        with open_db() as conn:
            for deck_card in deck_cards:
                row = conn.execute(
                    """
                    SELECT id, quantity
                    FROM collection_items
                    WHERE scryfall_id = ? AND finish = ?
                    """,
                    (deck_card["scryfall_id"], deck_card["finish"]),
                ).fetchone()
                if row is None:
                    continue
                take = min(int(row["quantity"]), int(deck_card["quantity"]))
                if take <= 0:
                    continue
                adjust_collection_quantity(
                    conn,
                    scryfall_id=deck_card["scryfall_id"],
                    finish=deck_card["finish"],
                    delta=-take,
                )
                touched_ids.add(deck_card["scryfall_id"])
                removed += take

            db_set_deck_owned(conn, file_name, False)
            deck_status = deck_owned_status(conn, file_name, deck)
            response = list_collection(conn)
            response["deck_remove"] = {
                "deck": {**deck_summary(deck, file_name), **deck_status},
                "removed_cards": removed,
            }
        invalidate_collection_blocks_cache(scryfall_ids=touched_ids or None, full_rebuild=not touched_ids)
        self.json_response(response)

    def set_deck_owned(self) -> None:
        payload = self.read_json()
        file_name = str(payload.get("file_name") or "").strip()
        if not file_name:
            raise ValueError("file_name est requis.")
        if not deck_file_in_catalog(file_name):
            raise ValueError("Deck introuvable.")
        owned = bool(payload.get("owned"))
        deck = fetch_deck(file_name)
        with open_db() as conn:
            db_set_deck_owned(conn, file_name, owned)
            status = deck_owned_status(conn, file_name, deck)
        self.json_response({"file_name": file_name, **status})

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

    def start_price_archive(self) -> None:
        payload = self.read_json(default={})
        force = bool(payload.get("force"))
        started = start_price_archive_job(force=force)
        status = price_archive_status_payload()
        status["started_now"] = started
        code = HTTPStatus.ACCEPTED if started else HTTPStatus.OK
        self.json_response(status, status=code)

    def price_archive_status(self) -> None:
        self.json_response(price_archive_status_payload())

    def start_startup_warmup(self) -> None:
        payload = self.read_json(default={})
        force = bool(payload.get("force"))
        started = start_startup_warmup_job(force=force)
        status = startup_warmup_status_payload()
        status["started_now"] = started
        code = HTTPStatus.ACCEPTED if started else HTTPStatus.OK
        self.json_response(status, status=code)

    def startup_warmup_status(self) -> None:
        self.json_response(startup_warmup_status_payload())

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
            client = ScryfallClient()
            try:
                card = refresh_card_from_scryfall(conn, client, scryfall_id)
                conn.commit()
            except ScryfallError:
                card = get_cached_card(conn, scryfall_id)
                if card is None:
                    raise
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
        invalidate_collection_blocks_cache(scryfall_ids={scryfall_id})
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
            row = conn.execute(
                "SELECT scryfall_id FROM collection_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            updated = update_collection_item(conn, item_id, payload)
            if not updated:
                self.json_response({"error": "Collection item not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.json_response(list_collection(conn))
        if row:
            invalidate_collection_blocks_cache(scryfall_ids={row["scryfall_id"]})
        else:
            invalidate_collection_blocks_cache(full_rebuild=True)

    def delete_from_collection(self, item_id: int) -> None:
        with open_db() as conn:
            row = conn.execute(
                "SELECT scryfall_id FROM collection_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            deleted = delete_collection_item(conn, item_id)
            if not deleted:
                self.json_response({"error": "Collection item not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.json_response(list_collection(conn))
        if row:
            invalidate_collection_blocks_cache(scryfall_ids={row["scryfall_id"]})
        else:
            invalidate_collection_blocks_cache(full_rebuild=True)

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
                cards_table = catalog_table("cards")
                rows = conn.execute(
                    f"SELECT scryfall_id FROM {cards_table} ORDER BY updated_at DESC LIMIT 100"
                ).fetchall()
                card_ids = [row["scryfall_id"] for row in rows]

            for scryfall_id in card_ids:
                card = client.card(scryfall_id)
                save_card(conn, card)
                snapshot_count += save_price_snapshots(conn, card)
                for finish in card.get("finishes") or ["nonfoil"]:
                    if finish in VALID_FINISHES:
                        snapshot_count += ensure_price_fallback(conn, client, card, finish)
                snapshot_count += sync_mtgjson_for_card(conn, card)
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

        client = ScryfallClient()
        with open_db() as conn:
            try:
                card = refresh_card_from_scryfall(conn, client, scryfall_id)
                conn.commit()
            except ScryfallError:
                card = get_cached_card(conn, scryfall_id)
                if card is None:
                    raise

            self.json_response(
                {
                    "card": card_summary(conn, card, finish),
                    "history": price_history(conn, scryfall_id, finish),
                },
                extra_headers={"Cache-Control": "no-store"},
            )

    def card_detail(self, scryfall_id: str, query: dict[str, list[str]]) -> None:
        finish = one(query, "finish", "nonfoil")
        if finish not in VALID_FINISHES:
            raise ValueError("Finition invalide.")

        client = ScryfallClient()
        rulings: list[dict[str, Any]] = []
        with open_db() as conn:
            try:
                card = refresh_card_from_scryfall(conn, client, scryfall_id)
                conn.commit()
                rulings = client.rulings(scryfall_id)
                client.throttle()
            except ScryfallError:
                card = get_cached_card(conn, scryfall_id)
                if card is None:
                    raise

            display_lang = parse_display_lang(query)
            language_siblings = language_sibling_ids(conn, card, client)
            display_id = resolve_display_card_id(card, language_siblings, display_lang)
            if display_id != card["id"]:
                try:
                    display_card = refresh_card_from_scryfall(conn, client, display_id)
                    conn.commit()
                except ScryfallError:
                    display_card = get_cached_card(conn, display_id) or card
            else:
                display_card = card

            summary = card_summary(conn, display_card, finish)
            effective_finish = summary.get("display_finish") or finish
            mtgjson_points, mtgjson_status = enrich_mtgjson_prices(conn, display_card)
            history = price_history_for_lang_mode(
                conn,
                display_card,
                effective_finish,
                display_lang,
                client=client,
            )
            conn.commit()
            other_printings = other_printing_summaries(conn, client, display_card, effective_finish)
            finish_variants = finish_variant_summaries(conn, client, card)
            catalog_blocks = catalog_locations_for_set(display_card.get("set") or "")
            oracle_owned = oracle_collection_summary(conn, display_card.get("oracle_id"))
            cm_scryfall_id = resolve_cardmarket_scryfall_id(conn, display_card)
            cm_guide = cardmarket_latest_guide_for_card(conn, cm_scryfall_id, effective_finish)
            cm_series = cardmarket_guide_multi_series(conn, cm_scryfall_id, effective_finish)
            cm_insights = cardmarket_product_insights(conn, display_card)
            if cm_insights:
                cm_insights = {
                    **cm_insights,
                    "product_url": cardmarket_product_url(int(cm_insights["id_product"])),
                }
            cm_payload = None
            live_point = current_eur_price(display_card, effective_finish)
            if cm_guide:
                foil_url = None
                if effective_finish != "foil":
                    foil_guide = cardmarket_latest_guide_for_card(conn, cm_scryfall_id, "foil")
                    if foil_guide and foil_guide.get("id_product"):
                        foil_url = cardmarket_product_url(foil_guide["id_product"], foil=True)
                live_delta_pct = None
                trend = (cm_guide.get("metrics") or {}).get("trend")
                if live_point is not None and trend and trend > 0:
                    live_delta_pct = round((float(live_point.price) - float(trend)) / float(trend) * 100, 1)
                cm_payload = {
                    **cm_guide,
                    "product_url": cardmarket_product_url(
                        cm_guide["id_product"],
                        foil=effective_finish == "foil",
                    ),
                    "foil_product_url": foil_url,
                    "live_price": float(live_point.price) if live_point else None,
                    "live_delta_pct": live_delta_pct,
                }
            self.json_response(
                {
                    "card": summary,
                    "details": card_details(display_card),
                    "rulings": rulings_to_json(rulings),
                    "history": history,
                    "cardmarket_series": cm_series,
                    "display_lang": display_lang,
                    "history_lang": display_lang,
                    "language_siblings": language_siblings,
                    "requested_scryfall_id": scryfall_id,
                    "periods": price_periods(history),
                    "collection": collection_quantities_for_card(conn, display_card["id"]),
                    "oracle_owned": oracle_owned,
                    "finish_variants": finish_variants,
                    "markets": market_summaries(mtgjson_points, effective_finish),
                    "cardmarket_guide": cm_payload,
                    "cardmarket_insights": cm_insights,
                    "mtgjson": mtgjson_status,
                    "other_printings": other_printings,
                    "catalog_blocks": catalog_blocks,
                },
                extra_headers={"Cache-Control": "no-store"},
            )

    def read_json(self, default: Any | None = None) -> Any:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length == 0:
            if default is not None:
                return default
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def json_response(
        self,
        payload: Any,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError):
            return

    def serve_cached_image(self, path: str) -> None:
        file_name = Path(path).name
        scryfall_id = file_name.rsplit(".", 1)[0]
        target = image_path(scryfall_id)
        if not target.exists():
            self.send_error(int(HTTPStatus.NOT_FOUND))
            return

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def serve_set_icon(self, path: str) -> None:
        file_name = Path(path).name
        slug = file_name.rsplit(".", 1)[0]
        self.serve_set_icon_slug(slug)

    def serve_set_icon_slug(self, slug: str) -> None:
        try:
            target = ensure_set_icon(slug, set_code=slug.upper())
        except (CacheError, HTTPError, URLError, TimeoutError, OSError):
            self.send_error(int(HTTPStatus.NOT_FOUND))
            return

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def serve_version_js(self) -> None:
        label = app_version_label()
        identity = version_identity()
        data = (
            f'window.MTG_APP_VERSION = "{label}";\n'
            f'window.MTG_PROJECT_SLUG = "{identity["projectSlug"]}";\n'
            f'window.MTG_VERSION_PACK_ID = "{identity["versionPackId"]}";\n'
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_build_info(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        target = repo_root / "public" / "build-info.json"
        if not target.exists():
            sync_build_info()
        if not target.exists():
            self.json_response(
                {
                    "label": app_version_label(),
                    "error": "build-info.json not generated — run npm run version:sync",
                },
                status=HTTPStatus.NOT_FOUND,
            )
            return
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path: str) -> None:
        if path.startswith("/cache/"):
            self.send_error(int(HTTPStatus.NOT_FOUND))
            return
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
    return refresh_card_from_scryfall(conn, client, scryfall_id)


def refresh_card_from_scryfall(conn, client: ScryfallClient, scryfall_id: str) -> dict[str, Any]:
    card = client.card(scryfall_id)
    save_card(conn, card)
    save_price_snapshots(conn, card)
    client.throttle()
    for finish in available_finishes_for_card(card):
        ensure_price_fallback(conn, client, card, finish)
    sync_mtgjson_for_card(conn, card)
    return card


def ensure_price_fallback(conn, client: ScryfallClient, card: dict[str, Any], finish: str) -> int:
    if current_eur_price(card, finish) is not None:
        return 0

    set_code = card.get("set")
    collector_number = card.get("collector_number")
    if not set_code or not collector_number or card.get("lang") == "en":
        return 0

    try:
        english_print = client.card_by_set_number_lang(set_code, collector_number, "en")
        client.throttle()
    except ScryfallError:
        return 0

    save_card(conn, english_print)
    save_price_snapshots(conn, english_print)

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


def sync_mtgjson_price_snapshots(
    conn,
    scryfall_id: str,
    price_entry: dict[str, Any],
) -> int:
    points = normalize_price_points(scryfall_id, price_entry)
    if not points or not mtgjson_snapshots_need_sync(conn, scryfall_id, points):
        return 0
    return save_external_price_snapshots(conn, points)


def sync_mtgjson_for_card(conn, card: dict[str, Any]) -> int:
    try:
        mtgjson_uuid = cached_mtgjson_uuid(conn, card["id"])
        if mtgjson_uuid is None:
            mtgjson_uuid = mtgjson_uuid_for_scryfall_card(card)
            if mtgjson_uuid is None:
                return 0
            save_mtgjson_uuid(
                conn,
                scryfall_id=card["id"],
                mtgjson_uuid=mtgjson_uuid,
                set_code=card.get("set"),
                collector_number=card.get("collector_number"),
            )

        price_entry = cached_mtgjson_price_entry(conn, mtgjson_uuid)
        if price_entry is None:
            price_entry = extract_price_entry(mtgjson_uuid)
            if price_entry is None:
                return 0
            save_mtgjson_price_entry(conn, mtgjson_uuid, price_entry)

        return sync_mtgjson_price_snapshots(conn, card["id"], price_entry)
    except MtgjsonError:
        return 0


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
        inserted = sync_mtgjson_price_snapshots(conn, card["id"], price_entry)
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
    snapshots_written = 0
    for deck_card in deck_cards:
        entry = entries.get(deck_card.get("mtgjson_uuid"))
        if entry is None:
            continue
        points.extend(normalize_price_points(deck_card["scryfall_id"], entry))
        snapshots_written += sync_mtgjson_price_snapshots(conn, deck_card["scryfall_id"], entry)

    conn.commit()
    status.update(
        {
            "available": bool(points),
            "cache_hits": len(uuids) - len(missing_uuids),
            "fetched": len(fetched_entries),
            "missing_uuids": len(set(missing_uuids) - set(fetched_entries)),
            "points": len(points),
            "snapshots_written": snapshots_written,
        }
    )
    return points, status


@dataclass
class HistoryBuildOptions:
    only_priced: bool = False
    exclude_added_after: str | None = None
    exclude_new_cards: bool = False
    price_mode: str = "owned"
    exclude_movers_common: bool = False
    exclude_movers_uncommon: bool = False
    exclude_movers_rare: bool = False
    exclude_movers_special: bool = False
    movers_min_end_price: float = 0.0
    exclude_illiquid: bool = False
    speculative_preset: str | None = None
    market_price_metric: str = "trend"
    history_mode: str = "auto"
    market_scope: str = "all"


MOVER_SPECIAL_RARITIES = frozenset({"mythic", "special", "bonus"})


CHART_RANGE_DAYS: dict[str, int] = {
    "7d": 7,
    "1m": 30,
    "6m": 183,
    "1y": 365,
    "5y": 1825,
}
COLLECTION_MOVERS_LIMIT = 8
MARKET_MOVERS_LIMIT = 10
MARKET_SPECULATIVE_PICKS_LIMIT = 10
MARKET_SPECULATIVE_MAX_START_EUR = Decimal("2")
MARKET_SPECULATIVE_MAX_END_EUR = Decimal("12")
MARKET_SPECULATIVE_MIN_END_EUR = Decimal("0.25")
MARKET_SPECULATIVE_MIN_PCT = 25.0
MARKET_SPECULATIVE_MIN_FLAT_EUR = Decimal("0.30")
MARKET_SPECULATIVE_MIN_SET_AGE_YEARS = 3.0
MARKET_SPECULATIVE_STABILITY_LOOKBACK_DAYS = 180
MARKET_SPECULATIVE_STABILITY_MAX_RANGE_EUR = Decimal("0.50")
MARKET_SPECULATIVE_STABILITY_MAX_RELATIVE_RANGE = 0.20
MARKET_SPECULATIVE_STABILITY_MIN_POINTS = 2
MARKET_SPECULATIVE_AGE_BONUS_BASE = 8.0
MARKET_SPECULATIVE_STABILITY_SPIKE_BONUS = 30.0
MARKET_SPECULATIVE_BREAKOUT_RATIO = 1.15
MARKET_SPECULATIVE_AVG7_DISCOUNT_RATIO = 0.92
MARKET_SPECULATIVE_MOMENTUM_BONUS = 12.0
MARKET_SPECULATIVE_LOW_SPREAD_MAX = 0.25
MARKET_SPECULATIVE_LOW_SPREAD_BONUS = 8.0
MARKET_LIQUIDITY_LOW_RATIO = 0.5
MARKET_LIQUIDITY_AVG1_DIVERGENCE = 2.0
SPECULATIVE_SIGNAL_PRESETS: dict[str, frozenset[str]] = {
    "stable_spike": frozenset({"ancienne", "prix_stable", "spike_sur_stabilite"}),
    "value_avg7": frozenset({"sous_avg7", "momentum"}),
    "breakout_liquid": frozenset({"breakout", "spread_etroit"}),
}
MARKET_PREMIUM_MIN_END_EUR = Decimal("10")
DEFAULT_MARKET_WARMUP_RANGES = ("7d", "1m")
MARKET_MOVERS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
MARKET_MOVERS_CACHE_LOCK = threading.Lock()
MARKET_MOVERS_CACHE_TTL = 6 * 3600.0
MARKET_MOVERS_META_PREFIX = "market_movers_cache:"
MARKET_SPECULATIVE_EVAL_LIMIT = 1500
MARKET_WARMUP_RANGE_PAUSE_SECONDS = 1.0
COLLECTION_HISTORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
COLLECTION_HISTORY_CACHE_LOCK = threading.Lock()
COLLECTION_HISTORY_CACHE_TTL = 6 * 3600.0
COLLECTION_HISTORY_CACHE_MAX_ENTRIES = 8


def parse_my_collection_page(query: dict[str, list[str]]) -> tuple[int, int]:
    raw_size = one(query, "page_size", "100").strip()
    try:
        page_size = int(raw_size)
    except ValueError:
        page_size = 100
    if page_size not in MY_COLLECTION_PAGE_SIZES:
        page_size = 100
    raw_offset = one(query, "offset", "0").strip()
    try:
        offset = max(0, int(raw_offset))
    except ValueError:
        offset = 0
    return page_size, offset


def collection_history_cache_key(
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
) -> str:
    payload = {
        "source_key": source_key,
        "range": range_key,
        "options": history_options_json(options),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def get_cached_collection_history(
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
) -> dict[str, Any] | None:
    key = collection_history_cache_key(source_key, options, range_key)
    now = time.time()
    with COLLECTION_HISTORY_CACHE_LOCK:
        entry = COLLECTION_HISTORY_CACHE.get(key)
        if entry is None:
            return None
        cached_at, payload = entry
        if now - cached_at > COLLECTION_HISTORY_CACHE_TTL:
            COLLECTION_HISTORY_CACHE.pop(key, None)
            return None
        return payload


def cache_collection_history(
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
    payload: dict[str, Any],
) -> None:
    key = collection_history_cache_key(source_key, options, range_key)
    with COLLECTION_HISTORY_CACHE_LOCK:
        if key not in COLLECTION_HISTORY_CACHE and len(COLLECTION_HISTORY_CACHE) >= COLLECTION_HISTORY_CACHE_MAX_ENTRIES:
            oldest_key = min(
                COLLECTION_HISTORY_CACHE,
                key=lambda cache_key: COLLECTION_HISTORY_CACHE[cache_key][0],
            )
            COLLECTION_HISTORY_CACHE.pop(oldest_key, None)
        COLLECTION_HISTORY_CACHE[key] = (time.time(), payload)


def invalidate_collection_history_cache() -> None:
    with COLLECTION_HISTORY_CACHE_LOCK:
        COLLECTION_HISTORY_CACHE.clear()


def parse_history_range(query: dict[str, list[str]]) -> str:
    range_key = one(query, "range", "7d").strip()
    if range_key not in CHART_RANGE_DAYS:
        return "7d"
    return range_key


def parse_history_options(query: dict[str, list[str]]) -> HistoryBuildOptions:
    only_priced = one(query, "only_priced", "0").lower() in {"1", "true", "yes", "on"}
    exclude_added_after = one(query, "exclude_added_after", "").strip() or None
    exclude_new_cards = one(query, "exclude_new_cards", "0").lower() in {"1", "true", "yes", "on"}
    exclude_movers_common = one(query, "exclude_movers_common", "0").lower() in {"1", "true", "yes", "on"}
    exclude_movers_uncommon = one(query, "exclude_movers_uncommon", "0").lower() in {"1", "true", "yes", "on"}
    exclude_movers_rare = one(query, "exclude_movers_rare", "0").lower() in {"1", "true", "yes", "on"}
    exclude_movers_special = one(query, "exclude_movers_special", "0").lower() in {"1", "true", "yes", "on"}
    price_mode = one(query, "price_mode", "owned").strip().lower()
    if price_mode not in {"owned", "nonfoil"}:
        price_mode = "owned"
    movers_min_end_price = max(0.0, float(one(query, "movers_min_end_price", "0") or "0"))
    exclude_illiquid = one(query, "exclude_illiquid", "0").lower() in {"1", "true", "yes", "on"}
    speculative_preset = one(query, "speculative_preset", "").strip() or None
    market_price_metric = one(query, "market_metric", "trend").strip().lower()
    if market_price_metric not in {"trend", "avg7"}:
        market_price_metric = "trend"
    history_mode = one(query, "history_mode", "auto").strip().lower()
    if history_mode not in {"auto", "fast", "archive"}:
        history_mode = "auto"
    market_scope = one(query, "scope", "all").strip().lower()
    if market_scope not in {"all", "owned", "wishlist"}:
        market_scope = "all"
    return HistoryBuildOptions(
        only_priced=only_priced,
        exclude_added_after=exclude_added_after,
        exclude_new_cards=exclude_new_cards,
        movers_min_end_price=movers_min_end_price,
        exclude_movers_common=exclude_movers_common,
        exclude_movers_uncommon=exclude_movers_uncommon,
        exclude_movers_rare=exclude_movers_rare,
        exclude_movers_special=exclude_movers_special,
        price_mode=price_mode,
        exclude_illiquid=exclude_illiquid,
        speculative_preset=speculative_preset,
        market_price_metric=market_price_metric,
        history_mode=history_mode,
        market_scope=market_scope,
    )


def price_finish_for_mode(owned_finish: str, price_mode: str) -> str:
    if price_mode == "nonfoil" and owned_finish in {"foil", "etched"}:
        return "nonfoil"
    return owned_finish


def scryfall_card_for_owned_line(conn, card_entry: dict[str, Any]) -> dict[str, Any] | None:
    cached = card_entry.get("_card")
    if cached is not None:
        return cached
    return get_cached_card(conn, card_entry["scryfall_id"])


def owned_line_price_point(
    conn,
    card_entry: dict[str, Any],
    options: HistoryBuildOptions,
) -> PricePoint | None:
    scryfall_card = scryfall_card_for_owned_line(conn, card_entry)
    if scryfall_card is None:
        return None
    owned_finish = card_entry["finish"]
    lookup_finish = price_finish_for_mode(owned_finish, options.price_mode)
    price_point = display_price_for(conn, scryfall_card, lookup_finish)
    if price_point is None and lookup_finish != owned_finish:
        price_point = display_price_for(conn, scryfall_card, owned_finish)
    if price_point is None or price_point.currency != "EUR":
        return None
    return price_point


def filter_cards_by_acquisition(
    cards: list[dict[str, Any]],
    exclude_added_after: str | None,
) -> list[dict[str, Any]]:
    if not exclude_added_after:
        return cards
    cutoff = exclude_added_after[:10]
    return [
        card
        for card in cards
        if (card.get("first_owned_at") or "1970-01-01T00:00:00Z")[:10] <= cutoff
    ]


def fetch_snapshot_price_points(
    conn,
    scryfall_ids: list[str],
    source_key: str,
) -> list[dict[str, Any]]:
    if not scryfall_ids:
        return []
    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    db_source = source_meta["source"]
    sources = [db_source]
    if source_key == "cardmarket":
        sources = [CARDMARKET_GUIDE_SOURCE, "scryfall-cardmarket", "mtgjson-cardmarket"]
    points: list[dict[str, Any]] = []
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        source_placeholders = ",".join("?" for _ in sources)
        snapshots_table = catalog_table("price_snapshots")
        snap_rows = conn.execute(
            f"""
            SELECT scryfall_id, finish, snapshot_date, price, source, currency, collected_at
            FROM {snapshots_table}
            WHERE currency = ?
              AND source IN ({source_placeholders})
              AND scryfall_id IN ({placeholders})
            """,
            (currency, *sources, *chunk),
        ).fetchall()
        for row in snap_rows:
            points.append(
                {
                    "scryfall_id": row["scryfall_id"],
                    "finish": row["finish"],
                    "snapshot_date": row["snapshot_date"],
                    "price": row["price"],
                    "source": row["source"],
                    "currency": row["currency"],
                    "collected_at": row["collected_at"],
                }
            )
    if source_key == "cardmarket":
        guide_points = cardmarket_guide_bulk_history_points(conn, scryfall_ids)
        points.extend(guide_points)
        return merge_collection_history_points(points)
    return points


def build_live_price_map(
    conn,
    cards: list[dict[str, Any]],
    options: HistoryBuildOptions,
) -> dict[tuple[str, str], Decimal]:
    live_prices: dict[tuple[str, str], Decimal] = {}
    for card in cards:
        price_point = owned_line_price_point(conn, card, options)
        if price_point is None:
            continue
        owned_finish = card["finish"]
        lookup_finish = price_finish_for_mode(owned_finish, options.price_mode)
        live_prices[(card["scryfall_id"], lookup_finish)] = price_point.price
        if owned_finish != lookup_finish:
            live_prices.setdefault((card["scryfall_id"], owned_finish), price_point.price)
    return live_prices


def build_live_today_points(
    conn,
    cards: list[dict[str, Any]],
    source_key: str,
    options: HistoryBuildOptions,
) -> list[dict[str, Any]]:
    if source_key != "cardmarket":
        return []
    today = date.today().isoformat()
    now = utc_now()
    live_points: list[dict[str, Any]] = []
    for (scryfall_id, finish), price in build_live_price_map(conn, cards, options).items():
        live_points.append(
            {
                "scryfall_id": scryfall_id,
                "finish": finish,
                "snapshot_date": today,
                "price": float(price),
                "source": "scryfall-cardmarket",
                "currency": "EUR",
                "collected_at": now,
            }
        )
    return live_points


def live_totals_for_cards(
    conn,
    cards: list[dict[str, Any]],
    options: HistoryBuildOptions,
) -> tuple[Decimal, int, int]:
    total = Decimal("0")
    priced_cards = 0
    missing_cards = 0
    for card in cards:
        quantity = int(card["quantity"])
        price_point = owned_line_price_point(conn, card, options)
        if price_point is None:
            if not options.only_priced:
                missing_cards += quantity
            continue
        total += price_point.price * quantity
        priced_cards += quantity
    return total, priced_cards, missing_cards


def upsert_today_history_point(
    history: list[dict[str, Any]],
    conn,
    cards: list[dict[str, Any]],
    options: HistoryBuildOptions,
    source_key: str,
) -> list[dict[str, Any]]:
    if source_key != "cardmarket" or not cards:
        return history
    today = date.today().isoformat()
    total, priced_cards, missing_cards = live_totals_for_cards(conn, cards, options)
    entry = {
        "snapshot_date": today,
        "total_eur": float(total),
        "priced_cards": priced_cards,
        "missing_cards": missing_cards,
    }
    if history and history[-1]["snapshot_date"] == today:
        history[-1] = entry
    else:
        history.append(entry)
    return sorted(history, key=lambda point: point["snapshot_date"])


def collection_cards_for_history(conn) -> list[dict[str, Any]]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT ci.scryfall_id, ci.finish, SUM(ci.quantity) AS quantity,
               MIN(ci.created_at) AS first_owned_at, c.raw_json
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
        GROUP BY ci.scryfall_id, ci.finish
        """
    ).fetchall()
    return [
        {
            "scryfall_id": row["scryfall_id"],
            "finish": row["finish"],
            "quantity": int(row["quantity"]),
            "first_owned_at": row["first_owned_at"],
            "_card": json.loads(row["raw_json"]),
        }
        for row in rows
    ]


def collection_valuation_history_fast(
    conn,
    source_key: str,
    options: HistoryBuildOptions,
    *,
    range_key: str,
    archive_meta: dict[str, Any],
) -> dict[str, Any]:
    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    source_label = source_meta["label"]
    all_cards = collection_cards_for_history(conn)
    collection_cards = filter_cards_by_acquisition(all_cards, options.exclude_added_after)
    total_lines_row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM collection_items WHERE quantity > 0"
    ).fetchone()
    total_lines = int(total_lines_row["quantity"])
    if not collection_cards:
        return {
            "current_total": 0.0,
            "current_total_eur": 0.0,
            "priced_cards": 0,
            "missing_cards": 0,
            "history": [],
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "history_mode": "fast",
            "archive_meta": archive_meta,
            "meta": {"total_lines": total_lines, "included_lines": 0, "fast_mode": True},
            "movers": [],
        }

    live_total, live_priced, live_missing = live_totals_for_cards(conn, collection_cards, options)
    today = date.today().isoformat()
    history = [
        {
            "date": today,
            "snapshot_date": today,
            "total_eur": float(live_total),
            "priced_cards": live_priced,
            "missing_cards": live_missing,
        }
    ]
    return {
        "current_total": float(live_total),
        "current_total_eur": float(live_total),
        "priced_cards": live_priced,
        "missing_cards": live_missing,
        "history": history,
        "history_source": f"{source_label} {currency} (approximatif)",
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "history_mode": "fast",
        "archive_meta": archive_meta,
        "meta": {
            "total_lines": total_lines,
            "included_lines": sum(card["quantity"] for card in collection_cards),
            "fast_mode": True,
            "range": range_key,
        },
        "movers": [],
    }


def collection_valuation_history(
    conn,
    source_key: str = "cardmarket",
    options: HistoryBuildOptions | None = None,
    range_key: str = "7d",
) -> dict[str, Any]:
    options = options or HistoryBuildOptions()
    from .collection_extras import cardmarket_archive_status

    archive_meta = cardmarket_archive_status(conn)
    resolved_mode = options.history_mode
    if resolved_mode == "auto":
        resolved_mode = "archive" if archive_meta["archive_days"] >= 7 else "fast"
    if resolved_mode == "fast":
        return collection_valuation_history_fast(
            conn,
            source_key,
            options,
            range_key=range_key,
            archive_meta=archive_meta,
        )
    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    source_label = source_meta["label"]
    all_cards = collection_cards_for_history(conn)
    collection_cards = filter_cards_by_acquisition(all_cards, options.exclude_added_after)
    catalogued_lines = sum(card["quantity"] for card in all_cards)
    total_lines_row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM collection_items WHERE quantity > 0"
    ).fetchone()
    total_lines = int(total_lines_row["quantity"])
    if not collection_cards:
        return {
            "current_total": 0.0,
            "current_total_eur": 0.0,
            "priced_cards": 0,
            "missing_cards": 0,
            "history": [],
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "meta": {
                "total_lines": total_lines,
                "included_lines": 0,
                "snapshot_lines": 0,
                "live_today_included": False,
            },
            "movers": collection_price_movers(
                conn,
                [],
                [],
                {},
                options,
                [],
                range_key,
                currency=currency,
                source_key=source_key,
            ),
        }

    scryfall_ids = sorted({card["scryfall_id"] for card in collection_cards})
    points = fetch_snapshot_price_points(conn, scryfall_ids, source_key)
    snapshot_lines = len({(p["scryfall_id"], p["finish"]) for p in points})
    live_points = build_live_today_points(conn, collection_cards, source_key, options)
    points.extend(live_points)
    live_prices = build_live_price_map(conn, collection_cards, options) if source_key == "cardmarket" else {}
    history = deck_history(
        collection_cards,
        points,
        options=options,
        live_prices=live_prices,
    )
    history = upsert_today_history_point(history, conn, collection_cards, options, source_key)
    period_bounds = snapshot_period_bounds(conn, source_key, range_key)
    history_cards = filter_cards_excluding_new_on_period(
        collection_cards,
        points,
        live_prices,
        options,
        history,
        range_key,
        period_bounds=period_bounds,
    )
    excluded_new_cards = (
        sum(card["quantity"] for card in collection_cards) - sum(card["quantity"] for card in history_cards)
        if options.exclude_new_cards
        else 0
    )
    if options.exclude_new_cards and excluded_new_cards > 0:
        history = deck_history(
            history_cards,
            points,
            options=options,
            live_prices=live_prices,
        )
        history = upsert_today_history_point(history, conn, history_cards, options, source_key)
    totals_cards = history_cards if options.exclude_new_cards else collection_cards
    live_total, live_priced, live_missing = (
        live_totals_for_cards(conn, totals_cards, options)
        if source_key == "cardmarket"
        else (Decimal("0"), 0, 0)
    )
    movers = collection_price_movers(
        conn,
        history_cards,
        points,
        live_prices,
        options,
        history,
        range_key,
        currency=currency,
        source_key=source_key,
    )
    meta = {
        "total_lines": total_lines,
        "catalogued_lines": catalogued_lines,
        "included_lines": sum(card["quantity"] for card in collection_cards),
        "snapshot_lines": snapshot_lines,
        "live_today_included": bool(live_points),
        "excluded_by_date": catalogued_lines - sum(card["quantity"] for card in collection_cards)
        if options.exclude_added_after
        else 0,
        "orphan_lines": max(0, total_lines - catalogued_lines),
        "excluded_new_cards": excluded_new_cards,
    }
    if history:
        latest = history[-1]
        current_total = float(live_total) if source_key == "cardmarket" else latest["total_eur"]
        priced_cards = live_priced if source_key == "cardmarket" else latest["priced_cards"]
        missing_cards = live_missing if source_key == "cardmarket" else latest["missing_cards"]
        return {
            "current_total": current_total,
            "current_total_eur": current_total,
            "priced_cards": priced_cards,
            "missing_cards": missing_cards,
            "history": history,
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "meta": meta,
            "history_mode": resolved_mode,
            "archive_meta": archive_meta,
        }

    return {
        "current_total": 0.0,
        "current_total_eur": 0.0,
        "priced_cards": 0,
        "missing_cards": sum(card["quantity"] for card in collection_cards),
        "history": [],
        "history_source": f"{source_label} {currency}",
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "meta": meta,
        "movers": movers,
    }


def deck_valuation_history_fast(
    conn,
    deck_cards: list[dict[str, Any]],
    source_key: str,
    options: HistoryBuildOptions,
    *,
    archive_meta: dict[str, Any],
) -> dict[str, Any]:
    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    source_label = source_meta["label"]
    if not deck_cards:
        return {
            "current_total_eur": 0.0,
            "priced_cards": 0,
            "missing_cards": 0,
            "history": [],
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "history_mode": "fast",
            "archive_meta": archive_meta,
            "meta": {"total_lines": 0, "included_lines": 0, "fast_mode": True},
        }

    live_total, live_priced, live_missing = live_totals_for_cards(conn, deck_cards, options)
    today = date.today().isoformat()
    history = [
        {
            "date": today,
            "snapshot_date": today,
            "total_eur": float(live_total),
            "priced_cards": live_priced,
            "missing_cards": live_missing,
        }
    ]
    return {
        "current_total_eur": float(live_total),
        "priced_cards": live_priced,
        "missing_cards": live_missing,
        "history": history,
        "history_source": f"{source_label} {currency} (approximatif)",
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "history_mode": "fast",
        "archive_meta": archive_meta,
        "meta": {
            "total_lines": sum(card["quantity"] for card in deck_cards),
            "included_lines": sum(card["quantity"] for card in deck_cards),
            "fast_mode": True,
        },
    }


def deck_valuation_history(
    conn,
    deck_cards: list[dict[str, Any]],
    source_key: str = "cardmarket",
    options: HistoryBuildOptions | None = None,
) -> dict[str, Any]:
    options = options or HistoryBuildOptions()
    from .collection_extras import cardmarket_archive_status

    archive_meta = cardmarket_archive_status(conn)
    resolved_mode = options.history_mode
    if resolved_mode == "auto":
        resolved_mode = "archive" if archive_meta["archive_days"] >= 7 else "fast"
    if resolved_mode == "fast":
        return deck_valuation_history_fast(conn, deck_cards, source_key, options, archive_meta=archive_meta)

    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    source_label = source_meta["label"]
    if not deck_cards:
        return {
            "current_total_eur": 0.0,
            "priced_cards": 0,
            "missing_cards": 0,
            "history": [],
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "meta": {"total_lines": 0, "included_lines": 0, "snapshot_lines": 0, "live_today_included": False},
        }

    scryfall_ids = sorted({card["scryfall_id"] for card in deck_cards})
    points = fetch_snapshot_price_points(conn, scryfall_ids, source_key)
    snapshot_lines = len({(p["scryfall_id"], p["finish"]) for p in points})
    live_points = build_live_today_points(conn, deck_cards, source_key, options)
    points.extend(live_points)
    live_prices = build_live_price_map(conn, deck_cards, options) if source_key == "cardmarket" else {}
    history = deck_history(
        deck_cards,
        points,
        options=options,
        live_prices=live_prices,
    )
    history = upsert_today_history_point(history, conn, deck_cards, options, source_key)
    live_total, live_priced, live_missing = (
        live_totals_for_cards(conn, deck_cards, options)
        if source_key == "cardmarket"
        else (Decimal("0"), 0, 0)
    )
    meta = {
        "total_lines": sum(card["quantity"] for card in deck_cards),
        "included_lines": sum(card["quantity"] for card in deck_cards),
        "snapshot_lines": snapshot_lines,
        "live_today_included": bool(live_points),
        "excluded_by_date": 0,
    }
    if history:
        latest = history[-1]
        current_total = float(live_total) if source_key == "cardmarket" else latest["total_eur"]
        priced_cards = live_priced if source_key == "cardmarket" else latest["priced_cards"]
        missing_cards = live_missing if source_key == "cardmarket" else latest["missing_cards"]
        return {
            "current_total_eur": current_total,
            "priced_cards": priced_cards,
            "missing_cards": missing_cards,
            "history": history,
            "history_source": f"{source_label} {currency}",
            "currency": currency,
            "source_key": source_key,
            "options": history_options_json(options),
            "meta": meta,
            "history_mode": resolved_mode,
            "archive_meta": archive_meta,
        }
    return {
        "current_total_eur": 0.0,
        "priced_cards": 0,
        "missing_cards": sum(card["quantity"] for card in deck_cards),
        "history": [],
        "history_source": f"{source_label} {currency}",
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "meta": meta,
        "history_mode": resolved_mode,
        "archive_meta": archive_meta,
    }


def history_options_json(options: HistoryBuildOptions) -> dict[str, Any]:
    return {
        "only_priced": options.only_priced,
        "exclude_added_after": options.exclude_added_after,
        "exclude_new_cards": options.exclude_new_cards,
        "price_mode": options.price_mode,
        "exclude_movers_common": options.exclude_movers_common,
        "exclude_movers_uncommon": options.exclude_movers_uncommon,
        "exclude_movers_rare": options.exclude_movers_rare,
        "exclude_movers_special": options.exclude_movers_special,
        "movers_min_end_price": options.movers_min_end_price,
        "exclude_illiquid": options.exclude_illiquid,
        "speculative_preset": options.speculative_preset,
        "market_metric": options.market_price_metric,
        "history_mode": options.history_mode,
        "scope": options.market_scope,
    }


def cardmarket_metrics_liquid(metrics: dict[str, float] | None) -> bool:
    if not metrics:
        return True
    trend = metrics.get("trend")
    low = metrics.get("low")
    avg1 = metrics.get("avg1")
    if trend and low and float(low) < float(trend) * MARKET_LIQUIDITY_LOW_RATIO:
        return False
    if trend and avg1 and float(avg1) > float(trend) * MARKET_LIQUIDITY_AVG1_DIVERGENCE:
        return False
    return True


def matches_speculative_preset(signals: list[str], preset: str | None) -> bool:
    if not preset:
        return True
    required = SPECULATIVE_SIGNAL_PRESETS.get(preset)
    if not required:
        return True
    signal_set = set(signals or [])
    return required.issubset(signal_set)


def market_movers_cache_key(source_key: str, options: HistoryBuildOptions, range_key: str) -> str:
    payload = {
        "source_key": source_key,
        "range": range_key,
        "options": history_options_json(options),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _market_movers_meta_key(source_key: str, options: HistoryBuildOptions, range_key: str) -> str:
    digest = market_movers_cache_key(source_key, options, range_key)
    return f"{MARKET_MOVERS_META_PREFIX}{digest}"


def load_persisted_market_movers(
    conn,
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
) -> dict[str, Any] | None:
    from .database import get_app_metadata

    raw = get_app_metadata(conn, _market_movers_meta_key(source_key, options, range_key))
    if not raw:
        return None
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return None
    guide_table = catalog_table("cardmarket_price_guide_daily")
    guide_max = conn.execute(f"SELECT MAX(snapshot_date) FROM {guide_table}").fetchone()
    guide_date = str(guide_max[0]) if guide_max and guide_max[0] else None
    if envelope.get("guide_max_date") != guide_date:
        return None
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else None


def persist_market_movers(
    conn,
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
    payload: dict[str, Any],
) -> None:
    from .database import set_app_metadata

    guide_table = catalog_table("cardmarket_price_guide_daily")
    guide_max = conn.execute(f"SELECT MAX(snapshot_date) FROM {guide_table}").fetchone()
    guide_date = str(guide_max[0]) if guide_max and guide_max[0] else None
    envelope = {
        "guide_max_date": guide_date,
        "cached_at": utc_now(),
        "payload": payload,
    }
    set_app_metadata(conn, _market_movers_meta_key(source_key, options, range_key), json.dumps(envelope))


def get_cached_market_movers(
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
) -> dict[str, Any] | None:
    key = market_movers_cache_key(source_key, options, range_key)
    now = time.time()
    with MARKET_MOVERS_CACHE_LOCK:
        entry = MARKET_MOVERS_CACHE.get(key)
        if entry is None:
            return None
        cached_at, payload = entry
        if now - cached_at > MARKET_MOVERS_CACHE_TTL:
            MARKET_MOVERS_CACHE.pop(key, None)
            return None
        return payload


def cache_market_movers(
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
    payload: dict[str, Any],
) -> None:
    key = market_movers_cache_key(source_key, options, range_key)
    with MARKET_MOVERS_CACHE_LOCK:
        MARKET_MOVERS_CACHE[key] = (time.time(), payload)


def invalidate_market_movers_cache() -> None:
    with MARKET_MOVERS_CACHE_LOCK:
        MARKET_MOVERS_CACHE.clear()


def warm_market_movers_cache(
    conn,
    *,
    source_key: str = "cardmarket",
    options: HistoryBuildOptions | None = None,
    ranges: tuple[str, ...] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    pause_between_ranges: float = MARKET_WARMUP_RANGE_PAUSE_SECONDS,
) -> dict[str, int]:
    build_options = options or HistoryBuildOptions()
    range_keys = ranges or DEFAULT_MARKET_WARMUP_RANGES
    stats = {"ranges_warmed": 0, "tracked_cards": 0}
    ranges_total = len(range_keys)
    for index, range_key in enumerate(range_keys, start=1):
        payload = market_price_movers(conn, source_key, build_options, range_key=range_key)
        cache_market_movers(source_key, build_options, range_key, payload)
        stats["ranges_warmed"] += 1
        stats["tracked_cards"] = max(stats["tracked_cards"], int(payload.get("tracked_cards") or 0))
        if on_progress:
            on_progress(
                {
                    "range": range_key,
                    "range_index": index,
                    "ranges_total": ranges_total,
                    "tracked_cards": stats["tracked_cards"],
                }
            )
        if index < ranges_total and pause_between_ranges > 0:
            time.sleep(pause_between_ranges)
    return stats


def card_line_rarity(conn, card_line: dict[str, Any]) -> str:
    scryfall_card = scryfall_card_for_owned_line(conn, card_line)
    if scryfall_card is None:
        return ""
    return str(scryfall_card.get("rarity") or "").lower()


def rarity_excluded_by_options(rarity: str, options: HistoryBuildOptions) -> bool:
    if options.exclude_movers_common and rarity == "common":
        return True
    if options.exclude_movers_uncommon and rarity == "uncommon":
        return True
    if options.exclude_movers_rare and rarity == "rare":
        return True
    if options.exclude_movers_special and rarity in MOVER_SPECIAL_RARITIES:
        return True
    return False


def batch_card_rarities(conn, scryfall_ids: list[str]) -> dict[str, str]:
    if not scryfall_ids:
        return {}
    cards_table = catalog_table("cards")
    rarities: dict[str, str] = {}
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT scryfall_id, rarity FROM {cards_table} WHERE scryfall_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for row in rows:
            rarities[row["scryfall_id"]] = str(row["rarity"] or "").lower()
    return rarities


def batch_card_set_codes(conn, scryfall_ids: list[str]) -> dict[str, str]:
    if not scryfall_ids:
        return {}
    cards_table = catalog_table("cards")
    set_codes: dict[str, str] = {}
    chunk_size = 400
    for index in range(0, len(scryfall_ids), chunk_size):
        chunk = scryfall_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT scryfall_id, set_code FROM {cards_table} WHERE scryfall_id IN ({placeholders})",
            chunk,
        ).fetchall()
        for row in rows:
            set_codes[row["scryfall_id"]] = str(row["set_code"] or "").upper()
    return set_codes


def batch_price_pre_period_stats(
    conn,
    scryfall_ids: list[str],
    *,
    source_key: str,
    before_date: str,
    lookback_days: int = MARKET_SPECULATIVE_STABILITY_LOOKBACK_DAYS,
    finish: str = "nonfoil",
) -> dict[str, dict[str, float]]:
    if not scryfall_ids:
        return {}
    if source_key == "cardmarket":
        guide_stats = cardmarket_guide_pre_period_stats(
            conn,
            scryfall_ids,
            before_date=before_date,
            lookback_days=lookback_days,
            finish=finish,
        )
        if len(guide_stats) >= len(scryfall_ids):
            return guide_stats
        snapshot_stats = _batch_snapshot_pre_period_stats(
            conn,
            scryfall_ids,
            source_key=source_key,
            before_date=before_date,
            lookback_days=lookback_days,
            finish=finish,
        )
        merged = dict(snapshot_stats)
        merged.update(guide_stats)
        return merged
    return _batch_snapshot_pre_period_stats(
        conn,
        scryfall_ids,
        source_key=source_key,
        before_date=before_date,
        lookback_days=lookback_days,
        finish=finish,
    )


def _batch_snapshot_pre_period_stats(
    conn,
    scryfall_ids: list[str],
    *,
    source_key: str,
    before_date: str,
    lookback_days: int = MARKET_SPECULATIVE_STABILITY_LOOKBACK_DAYS,
    finish: str = "nonfoil",
) -> dict[str, dict[str, float]]:
    if not scryfall_ids:
        return {}
    try:
        cutoff_date = (date.fromisoformat(before_date) - timedelta(days=lookback_days)).isoformat()
    except ValueError:
        return {}
    from .price_daily import column_for_chart_source, pre_period_stats_from_daily, reads_price_daily

    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    sources = chart_price_sources_for_key(source_key)
    stats: dict[str, dict[str, float]] = {}
    remaining_ids = list(scryfall_ids)
    if reads_price_daily(conn):
        primary_source = source_meta["source"]
        if primary_source == "cardmarket-guide":
            primary_source = "scryfall-cardmarket"
        column = column_for_chart_source(primary_source, finish)
        if column:
            stats = pre_period_stats_from_daily(
                conn,
                scryfall_ids,
                column=column,
                before_date=before_date,
                cutoff_date=cutoff_date,
            )
            remaining_ids = [scryfall_id for scryfall_id in scryfall_ids if scryfall_id not in stats]
            if not remaining_ids:
                return stats

    snapshot_tables: list[str] = []
    from .database import catalog_object_type

    snapshots = catalog_table("price_snapshots")
    if catalog_object_type(conn, "price_snapshots") in {"table", "view"}:
        snapshot_tables.append(snapshots)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone():
        snapshot_tables.append("price_snapshots_legacy")
    if not snapshot_tables:
        return stats

    chunk_size = 400
    source_placeholders = ",".join("?" for _ in sources)
    for index in range(0, len(remaining_ids), chunk_size):
        chunk = remaining_ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        union_queries = []
        for table in snapshot_tables:
            union_queries.append(
                f"""
                SELECT scryfall_id, price
                FROM {table}
                WHERE scryfall_id IN ({placeholders})
                  AND finish = ?
                  AND currency = ?
                  AND source IN ({source_placeholders})
                  AND snapshot_date < ?
                  AND snapshot_date >= ?
                  AND price > 0
                """
            )
        union_body = "\nUNION ALL\n".join(union_queries)
        params: list[Any] = []
        for _table in snapshot_tables:
            params.extend([*chunk, finish, currency, *sources, before_date, cutoff_date])
        rows = conn.execute(
            f"""
            SELECT scryfall_id,
                   MIN(price) AS min_price,
                   MAX(price) AS max_price,
                   AVG(price) AS avg_price,
                   COUNT(*) AS point_count
            FROM ({union_body}) AS combined
            GROUP BY scryfall_id
            """,
            tuple(params),
        ).fetchall()
        for row in rows:
            stats[row["scryfall_id"]] = {
                "min_price": float(row["min_price"]),
                "max_price": float(row["max_price"]),
                "avg_price": float(row["avg_price"] or 0),
                "point_count": float(row["point_count"]),
            }
    return stats


def mover_excluded_by_rarity(conn, card_line: dict[str, Any], options: HistoryBuildOptions) -> bool:
    if not any(
        (
            options.exclude_movers_common,
            options.exclude_movers_uncommon,
            options.exclude_movers_rare,
            options.exclude_movers_special,
        )
    ):
        return False
    rarity = card_line_rarity(conn, card_line)
    return rarity_excluded_by_options(rarity, options)


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


def merge_collection_history_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer Scryfall live, then Cardmarket guide, then MTGJSON snapshots for the same day."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_rank = {"scryfall-cardmarket": 0, CARDMARKET_GUIDE_SOURCE: 1, "mtgjson-cardmarket": 2}

    for point in points:
        key = (point["scryfall_id"], point["finish"], point["snapshot_date"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = point
            continue
        left_rank = source_rank.get(existing["source"], 99)
        right_rank = source_rank.get(point["source"], 99)
        if right_rank < left_rank:
            merged[key] = point
        elif right_rank == left_rank and str(point.get("collected_at") or "") > str(existing.get("collected_at") or ""):
            merged[key] = point

    return list(merged.values())


def price_on_or_before(dated_prices: dict[str, Decimal], snapshot_date: str) -> Decimal | None:
    best_date: str | None = None
    best_price: Decimal | None = None
    for date, price in dated_prices.items():
        if date <= snapshot_date and (best_date is None or date > best_date):
            best_date = date
            best_price = price
    return best_price


def build_price_point_maps(
    price_points: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Decimal]]:
    point_maps: dict[tuple[str, str], dict[str, Decimal]] = {}
    for point in price_points:
        key = (point["scryfall_id"], point["finish"])
        point_maps.setdefault(key, {})[point["snapshot_date"]] = Decimal(str(point["price"]))
    return point_maps


def unit_price_on_date(
    deck_card: dict[str, Any],
    snapshot_date: str,
    point_maps: dict[tuple[str, str], dict[str, Decimal]],
    live_prices: dict[tuple[str, str], Decimal],
    options: HistoryBuildOptions,
) -> Decimal | None:
    owned_finish = deck_card["finish"]
    lookup_finish = price_finish_for_mode(owned_finish, options.price_mode)
    price = price_on_or_before(
        point_maps.get((deck_card["scryfall_id"], lookup_finish), {}),
        snapshot_date,
    )
    if price is None and lookup_finish != owned_finish:
        price = price_on_or_before(
            point_maps.get((deck_card["scryfall_id"], owned_finish), {}),
            snapshot_date,
        )
    if price is None and live_prices:
        price = live_prices.get((deck_card["scryfall_id"], lookup_finish))
        if price is None and lookup_finish != owned_finish:
            price = live_prices.get((deck_card["scryfall_id"], owned_finish))
    return price


def history_period_bounds(
    history: list[dict[str, Any]],
    range_key: str,
) -> tuple[str, str] | None:
    if not history:
        return None
    sorted_history = sorted(history, key=lambda point: point["snapshot_date"])
    latest = sorted_history[-1]
    latest_date = date.fromisoformat(latest["snapshot_date"])
    days = CHART_RANGE_DAYS.get(range_key, 7)
    cutoff = (latest_date - timedelta(days=days)).isoformat()
    in_range = [point for point in sorted_history if point["snapshot_date"] >= cutoff]
    if not in_range:
        in_range = [latest]
    return in_range[0]["snapshot_date"], latest["snapshot_date"]


def chart_price_sources_for_key(source_key: str) -> tuple[str, ...]:
    source_meta = chart_price_source(source_key)
    if source_key == "cardmarket":
        return (CARDMARKET_GUIDE_SOURCE, "scryfall-cardmarket", "mtgjson-cardmarket")
    return (source_meta["source"],)


def snapshot_period_bounds(
    conn,
    source_key: str,
    range_key: str,
) -> tuple[str, str] | None:
    if source_key == "cardmarket":
        guide_bounds = cardmarket_guide_period_bounds(conn, range_key)
        if guide_bounds:
            return guide_bounds
    return _snapshot_period_bounds_from_table(conn, source_key, range_key)


def _snapshot_period_bounds_from_table(
    conn,
    source_key: str,
    range_key: str,
) -> tuple[str, str] | None:
    from .database import catalog_object_type
    from .price_daily import COLUMN_TO_SOURCE_FINISH, PRICE_DAILY_VALUE_COLUMNS, price_daily_date_bounds_for_columns

    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    sources = chart_price_sources_for_key(source_key)
    if catalog_object_type(conn, "price_snapshots") == "view":
        columns = [
            column
            for column in PRICE_DAILY_VALUE_COLUMNS
            if COLUMN_TO_SOURCE_FINISH[column][0] in sources
        ]
        bounds = price_daily_date_bounds_for_columns(conn, columns)
        if bounds:
            latest_date = date.fromisoformat(bounds[1])
            days = CHART_RANGE_DAYS.get(range_key, 7)
            cutoff = (latest_date - timedelta(days=days)).isoformat()
            start_date = bounds[0] if bounds[0] >= cutoff else cutoff
            return start_date, bounds[1]
    source_placeholders = ",".join("?" for _ in sources)
    snapshots_table = catalog_table("price_snapshots")
    latest_row = conn.execute(
        f"""
        SELECT MAX(snapshot_date) AS latest_date
        FROM {snapshots_table}
        WHERE currency = ?
          AND source IN ({source_placeholders})
        """,
        (currency, *sources),
    ).fetchone()
    if latest_row is None or not latest_row["latest_date"]:
        return None
    latest_date = date.fromisoformat(latest_row["latest_date"])
    days = CHART_RANGE_DAYS.get(range_key, 7)
    cutoff = (latest_date - timedelta(days=days)).isoformat()
    first_row = conn.execute(
        f"""
        SELECT MIN(snapshot_date) AS start_date
        FROM {snapshots_table}
        WHERE currency = ?
          AND source IN ({source_placeholders})
          AND snapshot_date >= ?
        """,
        (currency, *sources, cutoff),
    ).fetchone()
    if first_row is None or not first_row["start_date"]:
        return latest_row["latest_date"], latest_row["latest_date"]
    return first_row["start_date"], latest_row["latest_date"]


def scryfall_ids_priced_on_date(
    conn,
    source_key: str,
    snapshot_date: str,
    finish: str = "nonfoil",
) -> list[str]:
    source_meta = chart_price_source(source_key)
    sources = chart_price_sources_for_key(source_key)
    from .price_daily import column_for_chart_source, scryfall_ids_priced_on_daily_date, reads_price_daily

    if reads_price_daily(conn):
        primary_source = source_meta["source"]
        if primary_source == "cardmarket-guide":
            primary_source = "scryfall-cardmarket"
        column = column_for_chart_source(primary_source, finish)
        if column:
            return scryfall_ids_priced_on_daily_date(conn, snapshot_date, column)

    currency = source_meta["currency"]
    source_placeholders = ",".join("?" for _ in sources)
    snapshots_table = catalog_table("price_snapshots")
    rows = conn.execute(
        f"""
        SELECT DISTINCT scryfall_id
        FROM {snapshots_table}
        WHERE currency = ?
          AND source IN ({source_placeholders})
          AND finish = ?
          AND snapshot_date = ?
          AND price > 0
        """,
        (currency, *sources, finish, snapshot_date),
    ).fetchall()
    return [row["scryfall_id"] for row in rows]


def _price_was_stable_pre_period(stats: dict[str, float] | None) -> bool:
    if not stats:
        return False
    if int(stats.get("point_count", 0)) < MARKET_SPECULATIVE_STABILITY_MIN_POINTS:
        return False
    pre_min = float(stats["min_price"])
    pre_max = float(stats["max_price"])
    pre_range = pre_max - pre_min
    if pre_range <= float(MARKET_SPECULATIVE_STABILITY_MAX_RANGE_EUR):
        return True
    avg_price = float(stats.get("avg_price") or 0)
    if avg_price > 0 and pre_range / avg_price <= MARKET_SPECULATIVE_STABILITY_MAX_RELATIVE_RANGE:
        return True
    return False


def build_speculative_pick_context(
    item: dict[str, Any],
    *,
    set_code: str | None,
    pre_stats: dict[str, float] | None,
    as_of_date: str,
    cm_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    try:
        as_of = date.fromisoformat(as_of_date)
    except ValueError:
        as_of = date.today()
    age = set_age_years(set_code or "", as_of=as_of) if set_code else None
    pre_stable = _price_was_stable_pre_period(pre_stats)
    pre_max = float(pre_stats["max_price"]) if pre_stats else None
    end = float(item["end_price"])
    breakout = pre_max is not None and pre_max > 0 and end > pre_max * float(MARKET_SPECULATIVE_BREAKOUT_RATIO)
    context: dict[str, Any] = {
        "set_age_years": age,
        "pre_stable": pre_stable,
        "breakout": breakout,
        "pre_min": float(pre_stats["min_price"]) if pre_stats else None,
        "pre_max": pre_max,
        "cm_metrics": cm_metrics,
    }
    if cm_metrics:
        trend = cm_metrics.get("trend")
        avg7 = cm_metrics.get("avg7")
        avg30 = cm_metrics.get("avg30")
        low = cm_metrics.get("low")
        if trend is not None and avg7 is not None and avg7 > 0 and trend <= avg7 * MARKET_SPECULATIVE_AVG7_DISCOUNT_RATIO:
            context["sous_avg7"] = True
        if avg7 is not None and avg30 is not None and avg7 > avg30:
            context["momentum"] = True
        if trend is not None and low is not None and trend - low <= float(MARKET_SPECULATIVE_LOW_SPREAD_MAX):
            context["spread_etroit"] = True
    return context


def evaluate_speculative_pick(
    item: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Score cards with penny-stock entry and meaningful upside (speculation)."""
    start = float(item["start_price"])
    end = float(item["end_price"])
    pct = float(item["change_pct"])
    flat = float(item["change_flat"])
    if start >= float(MARKET_SPECULATIVE_MAX_START_EUR):
        return None
    if end > float(MARKET_SPECULATIVE_MAX_END_EUR) or end < float(MARKET_SPECULATIVE_MIN_END_EUR):
        return None
    if pct < MARKET_SPECULATIVE_MIN_PCT or flat < float(MARKET_SPECULATIVE_MIN_FLAT_EUR):
        return None

    score = pct + flat * 12.0
    signals: list[str] = []
    if context:
        age = context.get("set_age_years")
        is_old = age is not None and age >= MARKET_SPECULATIVE_MIN_SET_AGE_YEARS
        if is_old:
            signals.append("ancienne")
            score += MARKET_SPECULATIVE_AGE_BONUS_BASE + min(age - MARKET_SPECULATIVE_MIN_SET_AGE_YEARS, 7.0) * 2.0
        if context.get("pre_stable"):
            signals.append("prix_stable")
        if context.get("breakout"):
            signals.append("breakout")
        if is_old and context.get("pre_stable"):
            signals.append("spike_sur_stabilite")
            score += MARKET_SPECULATIVE_STABILITY_SPIKE_BONUS
        elif context.get("pre_stable") and context.get("breakout"):
            score += MARKET_SPECULATIVE_STABILITY_SPIKE_BONUS * 0.5
        if context.get("sous_avg7"):
            signals.append("sous_avg7")
            score += 10.0
        if context.get("momentum"):
            signals.append("momentum")
            score += MARKET_SPECULATIVE_MOMENTUM_BONUS
        if context.get("spread_etroit"):
            signals.append("spread_etroit")
            score += MARKET_SPECULATIVE_LOW_SPREAD_BONUS

    deduped: list[str] = []
    seen: set[str] = set()
    for signal in signals:
        if signal not in seen:
            seen.add(signal)
            deduped.append(signal)
    return {"score": score, "signals": deduped}


def speculative_pick_score(
    item: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> float | None:
    result = evaluate_speculative_pick(item, context)
    return None if result is None else float(result["score"])


def select_speculative_picks(
    movers_raw: list[dict[str, Any]],
    *,
    conn=None,
    source_key: str = "cardmarket",
    start_date: str | None = None,
    as_of_date: str | None = None,
    limit: int = MARKET_SPECULATIVE_PICKS_LIMIT,
    options: HistoryBuildOptions | None = None,
) -> list[dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    cm_latest: dict[str, dict[str, Any]] = {}
    eval_pool = movers_raw
    if len(movers_raw) > MARKET_SPECULATIVE_EVAL_LIMIT:
        eval_pool = sorted(
            movers_raw,
            key=lambda item: abs(float(item.get("change_pct") or 0)),
            reverse=True,
        )[:MARKET_SPECULATIVE_EVAL_LIMIT]
    if conn is not None and start_date:
        scryfall_ids = [row["scryfall_id"] for row in eval_pool if row.get("scryfall_id")]
        set_codes = batch_card_set_codes(conn, scryfall_ids)
        pre_stats = batch_price_pre_period_stats(
            conn,
            scryfall_ids,
            source_key=source_key,
            before_date=start_date,
        )
        cm_latest = (
            batch_cardmarket_latest_guide(conn, scryfall_ids, finish="nonfoil")
            if source_key == "cardmarket"
            else {}
        )
        reference_date = as_of_date or start_date
        for item in eval_pool:
            card_id = item.get("scryfall_id")
            if not card_id:
                continue
            cm_entry = cm_latest.get(card_id)
            contexts[card_id] = build_speculative_pick_context(
                item,
                set_code=set_codes.get(card_id),
                pre_stats=pre_stats.get(card_id),
                as_of_date=reference_date,
                cm_metrics=cm_entry.get("metrics") if cm_entry else None,
            )

    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in eval_pool:
        card_id = item.get("scryfall_id")
        cm_entry = cm_latest.get(card_id) if card_id and source_key == "cardmarket" else None
        if options and options.exclude_illiquid and cm_entry:
            if not cardmarket_metrics_liquid(cm_entry.get("metrics")):
                continue
        evaluation = evaluate_speculative_pick(item, contexts.get(card_id) if card_id else None)
        if evaluation is None:
            continue
        if not matches_speculative_preset(evaluation["signals"], options.speculative_preset if options else None):
            continue
        enriched = {
            **item,
            "speculative_score": round(evaluation["score"], 1),
            "speculative_signals": evaluation["signals"],
        }
        if cm_entry and cm_entry.get("metrics"):
            enriched["cardmarket_metrics"] = cm_entry["metrics"]
        ranked.append((evaluation["score"], enriched))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def enrich_speculative_picks(
    conn,
    picks_raw: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in picks_raw:
        entry = mover_entry_json(
            conn,
            {"scryfall_id": item["scryfall_id"], "finish": "nonfoil", "quantity": 1},
            start_price=Decimal(str(item["start_price"])),
            end_price=Decimal(str(item["end_price"])),
            start_date=start_date,
            end_date=end_date,
        )
        if "speculative_score" in item:
            entry["speculative_score"] = item["speculative_score"]
        if item.get("speculative_signals"):
            entry["speculative_signals"] = item["speculative_signals"]
        if item.get("cardmarket_metrics"):
            entry["cardmarket_metrics"] = item["cardmarket_metrics"]
        enriched.append(entry)
    return enriched


def market_mover_candidate_rows(
    conn,
    source_key: str,
    start_date: str,
    end_date: str,
    *,
    finish: str = "nonfoil",
    eligible_set_codes: frozenset[str] | None = None,
    price_metric: str = "trend",
) -> list[Any]:
    if source_key == "cardmarket":
        guide_rows = market_mover_rows_from_guide(
            conn,
            start_date,
            end_date,
            finish=finish,
            eligible_set_codes=eligible_set_codes,
            price_metric=price_metric,
        )
        if guide_rows:
            return guide_rows
    return market_mover_rows_from_snapshots(
        conn,
        source_key,
        start_date,
        end_date,
        finish=finish,
        eligible_set_codes=eligible_set_codes,
    )


def market_mover_rows_from_guide(
    conn,
    start_date: str,
    end_date: str,
    *,
    finish: str = "nonfoil",
    eligible_set_codes: frozenset[str] | None = None,
    price_metric: str = "trend",
) -> list[Any]:
    from .database import cardmarket_guide_columns

    codes = eligible_set_codes if eligible_set_codes is not None else market_eligible_set_codes()
    if not codes:
        return []
    columns = cardmarket_guide_columns(finish)
    metric_map = {"trend": columns["chart"], "avg7": columns["avg7"]}
    chart_column = metric_map.get(price_metric) or columns["chart"]
    map_table = catalog_table("cardmarket_product_map")
    guide_table = catalog_table("cardmarket_price_guide_daily")
    cards_table = catalog_table("cards")
    set_placeholders = ",".join("?" for _ in codes)
    set_params = tuple(sorted(codes))
    rows = conn.execute(
        f"""
        WITH eligible_cards AS (
            SELECT scryfall_id
            FROM {cards_table}
            WHERE upper(set_code) IN ({set_placeholders})
        )
        SELECT m.scryfall_id,
               s.{chart_column} AS start_price,
               e.{chart_column} AS end_price
        FROM {map_table} m
        INNER JOIN eligible_cards ec ON ec.scryfall_id = m.scryfall_id
        INNER JOIN {guide_table} s
                ON s.id_product = m.id_product
               AND s.snapshot_date = ?
               AND s.{chart_column} IS NOT NULL
               AND s.{chart_column} > 0
        INNER JOIN {guide_table} e
                ON e.id_product = m.id_product
               AND e.snapshot_date = ?
               AND e.{chart_column} IS NOT NULL
               AND e.{chart_column} > 0
        """,
        (*set_params, start_date, end_date),
    ).fetchall()
    return rows


def market_mover_rows_from_snapshots(
    conn,
    source_key: str,
    start_date: str,
    end_date: str,
    *,
    finish: str = "nonfoil",
    eligible_set_codes: frozenset[str] | None = None,
) -> list[Any]:
    codes = eligible_set_codes if eligible_set_codes is not None else market_eligible_set_codes()
    if not codes:
        return []
    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    sources = chart_price_sources_for_key(source_key)
    from .price_daily import column_for_chart_source, market_mover_rows_from_daily_column, reads_price_daily

    if reads_price_daily(conn) and len(sources) == 1:
        column = column_for_chart_source(sources[0], finish)
        if column:
            return market_mover_rows_from_daily_column(
                conn,
                column=column,
                start_date=start_date,
                end_date=end_date,
                eligible_set_codes=codes,
            )

    snapshots = catalog_table("price_snapshots")
    cards_table = catalog_table("cards")
    source_placeholders = ",".join("?" for _ in sources)
    set_placeholders = ",".join("?" for _ in codes)
    set_params = tuple(sorted(codes))
    source_rank_sql = """
        CASE source
          WHEN 'scryfall-cardmarket' THEN 0
          WHEN 'mtgjson-cardmarket' THEN 1
          ELSE 2
        END
    """
    start_source_rank_sql = """
        CASE ps.source
          WHEN 'scryfall-cardmarket' THEN 0
          WHEN 'mtgjson-cardmarket' THEN 1
          ELSE 2
        END
    """
    if len(sources) == 1:
        db_source = sources[0]
        return conn.execute(
            f"""
            WITH eligible_cards AS (
                SELECT scryfall_id
                FROM {cards_table}
                WHERE upper(set_code) IN ({set_placeholders})
            ),
            start_snap AS (
                SELECT ps.scryfall_id, MAX(ps.snapshot_date) AS snapshot_date
                FROM {snapshots} ps
                INNER JOIN eligible_cards ec ON ec.scryfall_id = ps.scryfall_id
                WHERE ps.finish = ?
                  AND ps.currency = ?
                  AND ps.source = ?
                  AND ps.snapshot_date <= ?
                  AND ps.price > 0
                GROUP BY ps.scryfall_id
            )
            SELECT e.scryfall_id,
                   s.price AS start_price,
                   e.price AS end_price
            FROM {snapshots} e
            INNER JOIN eligible_cards ec ON ec.scryfall_id = e.scryfall_id
            INNER JOIN start_snap st ON st.scryfall_id = e.scryfall_id
            INNER JOIN {snapshots} s
                    ON s.scryfall_id = st.scryfall_id
                   AND s.snapshot_date = st.snapshot_date
                   AND s.finish = ?
                   AND s.currency = ?
                   AND s.source = ?
            WHERE e.finish = ?
              AND e.currency = ?
              AND e.source = ?
              AND e.snapshot_date = ?
              AND e.price > 0
              AND s.price > 0
            """,
            (
                *set_params,
                finish,
                currency,
                db_source,
                start_date,
                finish,
                currency,
                db_source,
                finish,
                currency,
                db_source,
                end_date,
            ),
        ).fetchall()

    return conn.execute(
        f"""
        WITH eligible_cards AS (
            SELECT scryfall_id
            FROM {cards_table}
            WHERE upper(set_code) IN ({set_placeholders})
        ),
        end_ranked AS (
            SELECT ps.scryfall_id, ps.price AS end_price, ps.source,
              ROW_NUMBER() OVER (
                PARTITION BY ps.scryfall_id
                ORDER BY {source_rank_sql}
              ) AS rank
            FROM {snapshots} ps
            INNER JOIN eligible_cards ec ON ec.scryfall_id = ps.scryfall_id
            WHERE ps.finish = ?
              AND ps.currency = ?
              AND ps.source IN ({source_placeholders})
              AND ps.snapshot_date = ?
              AND ps.price > 0
        ),
        end_best AS (
            SELECT scryfall_id, end_price
            FROM end_ranked
            WHERE rank = 1
        ),
        start_ranked AS (
            SELECT ps.scryfall_id, ps.price AS start_price,
              ROW_NUMBER() OVER (
                PARTITION BY ps.scryfall_id
                ORDER BY {start_source_rank_sql}
              ) AS rank
            FROM {snapshots} ps
            INNER JOIN end_best e ON e.scryfall_id = ps.scryfall_id
            WHERE ps.finish = ?
              AND ps.currency = ?
              AND ps.source IN ({source_placeholders})
              AND ps.snapshot_date = ?
              AND ps.price > 0
        )
        SELECT s.scryfall_id, s.start_price, e.end_price
        FROM start_ranked s
        INNER JOIN end_best e ON e.scryfall_id = s.scryfall_id
        WHERE s.rank = 1
          AND s.start_price > 0
          AND e.end_price > 0
        """,
        (
            *set_params,
            finish,
            currency,
            *sources,
            end_date,
            finish,
            currency,
            *sources,
            start_date,
        ),
    ).fetchall()


def enrich_market_movers(
    conn,
    movers_raw: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in movers_raw:
        enriched.append(
            mover_entry_json(
                conn,
                {"scryfall_id": item["scryfall_id"], "finish": "nonfoil", "quantity": 1},
                start_price=Decimal(str(item["start_price"])),
                end_price=Decimal(str(item["end_price"])),
                start_date=start_date,
                end_date=end_date,
            )
        )
    return enriched


def market_price_movers(
    conn,
    source_key: str,
    options: HistoryBuildOptions,
    range_key: str,
    *,
    limit: int = MARKET_MOVERS_LIMIT,
) -> dict[str, Any]:
    cached = get_cached_market_movers(source_key, options, range_key)
    if cached is not None:
        return cached
    persisted = load_persisted_market_movers(conn, source_key, options, range_key)
    if persisted is not None:
        cache_market_movers(source_key, options, range_key, persisted)
        return persisted

    source_meta = chart_price_source(source_key)
    currency = source_meta["currency"]
    bounds = snapshot_period_bounds(conn, source_key, range_key)
    eligible_sets = market_eligible_set_codes()
    scope = {
        "min_release_date": MARKET_MIN_RELEASE_DATE,
        "label": "Extensions depuis Strixhaven (toutes cartes, pas seulement la collection)",
        "eligible_sets": len(eligible_sets),
    }
    empty = {
        "range": range_key,
        "start_date": None,
        "end_date": None,
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "scope": scope,
        "tracked_cards": 0,
        "top_flat_gain": [],
        "top_flat_loss": [],
        "top_pct_gain": [],
        "top_pct_loss": [],
        "top_speculative_pct_gain": [],
        "top_premium_flat_gain": [],
        "top_speculative_picks": [],
        "excluded_by_rarity": 0,
    }
    if bounds is None:
        return empty
    start_date, end_date = bounds
    candidates = market_mover_candidate_rows(
        conn,
        source_key,
        start_date,
        end_date,
        finish="nonfoil",
        eligible_set_codes=eligible_sets,
        price_metric=options.market_price_metric,
    )
    if not candidates:
        return {**empty, "start_date": start_date, "end_date": end_date}
    if options.market_scope == "owned":
        from .collection_extras import owned_scryfall_id_set

        allowed = owned_scryfall_id_set(conn)
        candidates = [row for row in candidates if row["scryfall_id"] in allowed]
        scope["label"] = "Cartes de ma collection"
        scope["filter"] = "owned"
    elif options.market_scope == "wishlist":
        from .collection_extras import wishlist_scryfall_id_set

        allowed = wishlist_scryfall_id_set(conn)
        candidates = [row for row in candidates if row["scryfall_id"] in allowed]
        scope["label"] = "Cartes de ma wishlist"
        scope["filter"] = "wishlist"
    if not candidates:
        return {**empty, "start_date": start_date, "end_date": end_date}
    filter_by_rarity = any(
        (
            options.exclude_movers_common,
            options.exclude_movers_uncommon,
            options.exclude_movers_rare,
            options.exclude_movers_special,
        )
    )
    rarity_by_id = (
        batch_card_rarities(conn, [row["scryfall_id"] for row in candidates])
        if filter_by_rarity
        else {}
    )
    movers_raw: list[dict[str, Any]] = []
    excluded_by_rarity = 0
    for row in candidates:
        if filter_by_rarity and rarity_excluded_by_options(rarity_by_id.get(row["scryfall_id"], ""), options):
            excluded_by_rarity += 1
            continue
        start_price = Decimal(str(row["start_price"]))
        end_price = Decimal(str(row["end_price"]))
        if options.movers_min_end_price > 0 and float(end_price) < options.movers_min_end_price:
            continue
        change_flat = end_price - start_price
        movers_raw.append(
            {
                "scryfall_id": row["scryfall_id"],
                "start_price": float(start_price),
                "end_price": float(end_price),
                "change_flat": float(change_flat),
                "change_pct": float((change_flat / start_price) * Decimal("100")),
            }
        )
    speculative_cap = float(MARKET_SPECULATIVE_MAX_START_EUR)
    premium_min = float(MARKET_PREMIUM_MIN_END_EUR)
    speculative = [item for item in movers_raw if item["start_price"] < speculative_cap]
    premium = [item for item in movers_raw if item["end_price"] >= premium_min]
    speculative_picks_raw = select_speculative_picks(
        movers_raw,
        conn=conn,
        source_key=source_key,
        start_date=start_date,
        as_of_date=end_date,
        options=options,
    )
    payload = {
        "range": range_key,
        "start_date": start_date,
        "end_date": end_date,
        "currency": currency,
        "source_key": source_key,
        "options": history_options_json(options),
        "scope": scope,
        "tracked_cards": len(candidates),
        "top_flat_gain": enrich_market_movers(
            conn,
            sorted(movers_raw, key=lambda item: item["change_flat"], reverse=True)[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_flat_loss": enrich_market_movers(
            conn,
            sorted(movers_raw, key=lambda item: item["change_flat"])[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_pct_gain": enrich_market_movers(
            conn,
            sorted(movers_raw, key=lambda item: item["change_pct"], reverse=True)[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_pct_loss": enrich_market_movers(
            conn,
            sorted(movers_raw, key=lambda item: item["change_pct"])[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_speculative_pct_gain": enrich_market_movers(
            conn,
            sorted(speculative, key=lambda item: item["change_pct"], reverse=True)[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_premium_flat_gain": enrich_market_movers(
            conn,
            sorted(premium, key=lambda item: item["change_flat"], reverse=True)[:limit],
            start_date=start_date,
            end_date=end_date,
        ),
        "top_speculative_picks": enrich_speculative_picks(
            conn,
            speculative_picks_raw,
            start_date=start_date,
            end_date=end_date,
        ),
        "excluded_by_rarity": excluded_by_rarity,
    }
    cache_market_movers(source_key, options, range_key, payload)
    persist_market_movers(conn, source_key, options, range_key, payload)
    return payload


def mover_entry_json(
    conn,
    card_line: dict[str, Any],
    *,
    start_price: Decimal,
    end_price: Decimal,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    change_flat = end_price - start_price
    change_pct = float((change_flat / start_price) * Decimal("100"))
    scryfall_card = scryfall_card_for_owned_line(conn, card_line)
    name = card_line["scryfall_id"]
    set_code = ""
    collector_number = ""
    image_url = catalog_image_url(card_line["scryfall_id"])
    if scryfall_card:
        name = scryfall_card.get("printed_name") or scryfall_card.get("name") or name
        set_code = scryfall_card.get("set") or ""
        collector_number = scryfall_card.get("collector_number") or ""
    return {
        "scryfall_id": card_line["scryfall_id"],
        "name": name,
        "set_code": set_code,
        "collector_number": collector_number,
        "finish": card_line["finish"],
        "quantity": int(card_line["quantity"]),
        "start_date": start_date,
        "end_date": end_date,
        "start_price": float(start_price),
        "end_price": float(end_price),
        "change_flat": float(change_flat),
        "change_pct": change_pct,
        "image_url": image_url,
    }


def is_new_card_on_period(
    card_line: dict[str, Any],
    start_date: str,
    end_date: str,
    point_maps: dict[tuple[str, str], dict[str, Decimal]],
    live_prices: dict[tuple[str, str], Decimal],
    options: HistoryBuildOptions,
) -> bool:
    start_price = unit_price_on_date(card_line, start_date, point_maps, live_prices, options)
    end_price = unit_price_on_date(card_line, end_date, point_maps, live_prices, options)
    if end_price is None or end_price <= 0:
        return False
    return start_price is None or start_price <= 0


def filter_cards_excluding_new_on_period(
    collection_cards: list[dict[str, Any]],
    price_points: list[dict[str, Any]],
    live_prices: dict[tuple[str, str], Decimal],
    options: HistoryBuildOptions,
    history: list[dict[str, Any]],
    range_key: str,
    *,
    period_bounds: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not options.exclude_new_cards:
        return collection_cards
    bounds = period_bounds or history_period_bounds(history, range_key)
    if bounds is None:
        return collection_cards
    start_date, end_date = bounds
    point_maps = build_price_point_maps(price_points)
    return [
        card_line
        for card_line in collection_cards
        if not is_new_card_on_period(card_line, start_date, end_date, point_maps, live_prices, options)
    ]


def collection_price_movers(
    conn,
    collection_cards: list[dict[str, Any]],
    price_points: list[dict[str, Any]],
    live_prices: dict[tuple[str, str], Decimal],
    options: HistoryBuildOptions,
    history: list[dict[str, Any]],
    range_key: str,
    *,
    currency: str,
    source_key: str = "cardmarket",
    limit: int = COLLECTION_MOVERS_LIMIT,
) -> dict[str, Any]:
    bounds = snapshot_period_bounds(conn, source_key, range_key)
    if bounds is None:
        bounds = history_period_bounds(history, range_key)
    empty = {
        "range": range_key,
        "start_date": None,
        "end_date": None,
        "currency": currency,
        "top_flat_gain": [],
        "top_flat_loss": [],
        "top_pct_gain": [],
        "top_pct_loss": [],
        "excluded_by_rarity": 0,
    }
    if bounds is None:
        return empty
    start_date, end_date = bounds
    point_maps = build_price_point_maps(price_points)
    movers: list[dict[str, Any]] = []
    excluded_by_rarity = 0
    for card_line in collection_cards:
        if mover_excluded_by_rarity(conn, card_line, options):
            excluded_by_rarity += int(card_line["quantity"])
            continue
        start_price = unit_price_on_date(card_line, start_date, point_maps, live_prices, options)
        end_price = unit_price_on_date(card_line, end_date, point_maps, live_prices, options)
        if options.exclude_new_cards and is_new_card_on_period(
            card_line, start_date, end_date, point_maps, live_prices, options
        ):
            continue
        if start_price is None or end_price is None:
            continue
        if start_price <= 0 or end_price <= 0:
            continue
        movers.append(
            mover_entry_json(
                conn,
                card_line,
                start_price=start_price,
                end_price=end_price,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return {
        "range": range_key,
        "start_date": start_date,
        "end_date": end_date,
        "currency": currency,
        "top_flat_gain": sorted(movers, key=lambda item: item["change_flat"], reverse=True)[:limit],
        "top_flat_loss": sorted(movers, key=lambda item: item["change_flat"])[:limit],
        "top_pct_gain": sorted(movers, key=lambda item: item["change_pct"], reverse=True)[:limit],
        "top_pct_loss": sorted(movers, key=lambda item: item["change_pct"])[:limit],
        "excluded_by_rarity": excluded_by_rarity,
    }


def deck_history(
    deck_cards: list[dict[str, Any]],
    price_points: list[dict[str, Any]],
    *,
    options: HistoryBuildOptions | None = None,
    live_prices: dict[tuple[str, str], Decimal] | None = None,
) -> list[dict[str, Any]]:
    options = options or HistoryBuildOptions()
    live_prices = live_prices or {}
    point_maps = build_price_point_maps(price_points)

    all_dates = sorted({date for point_map in point_maps.values() for date in point_map})
    if live_prices:
        today = date.today().isoformat()
        if today not in all_dates:
            all_dates.append(today)
        all_dates.sort()
    history: list[dict[str, Any]] = []
    for snapshot_date in all_dates:
        total = Decimal("0")
        priced_cards = 0
        missing_cards = 0
        for deck_card in deck_cards:
            quantity = int(deck_card["quantity"])
            price = unit_price_on_date(deck_card, snapshot_date, point_maps, live_prices, options)
            if price is None:
                if options.only_priced:
                    continue
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
    def on_status(updates: dict[str, Any]) -> None:
        update_preload_status(**updates)

    try:
        update_preload_status(running=True, started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        result = preload_commander_decks(
            limit=limit,
            commander_only=True,
            download_images=True,
            on_status=on_status,
        )
        update_preload_status(
            running=False,
            finished_at=result.get("finished_at"),
            decks_total=result.get("decks_total", 0),
            decks_processed=result.get("decks_processed", 0),
            unique_uuids=result.get("unique_uuids", 0),
            cached_uuids=result.get("cached_uuids", 0),
            fetched_uuids=result.get("fetched_uuids", 0),
            missing_uuids=result.get("missing_uuids", 0),
            scryfall_cards_cached=result.get("scryfall_cards_cached", 0),
            points=result.get("points", 0),
            snapshots_written=result.get("snapshots_written", 0),
            images_downloaded=result.get("images_downloaded", 0),
            images_skipped=result.get("images_skipped", 0),
            images_failed=result.get("images_failed", 0),
            error=result.get("error"),
        )
    except Exception as error:  # noqa: BLE001 - background status should capture any failure.
        update_preload_status(
            running=False,
            error=str(error),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


def price_archive_status_payload() -> dict[str, Any]:
    with ARCHIVE_LOCK:
        status = dict(ARCHIVE_STATUS)
    with open_db() as conn:
        from .database import get_app_metadata

        status.setdefault("last_archive_date", get_app_metadata(conn, "last_price_archive_date"))
        status.setdefault(
            "last_archive_finished_at",
            get_app_metadata(conn, "last_price_archive_finished_at"),
        )
        status["cardmarket"] = cardmarket_mapping_stats(conn)
    return status


def update_price_archive_status(**updates: Any) -> None:
    with ARCHIVE_LOCK:
        ARCHIVE_STATUS.update(updates)


def start_price_archive_job(*, force: bool = False) -> bool:
    with ARCHIVE_LOCK:
        if ARCHIVE_STATUS["running"]:
            return False
        ARCHIVE_STATUS.update(
            {
                "running": True,
                "phase": "starting",
                "message": "Demarrage de l'archivage...",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "finished_at": None,
                "error": None,
                "skipped": False,
                "uuids_total": 0,
                "uuids_found": 0,
                "cards_processed": 0,
                "cards_total": 0,
                "snapshots_written": 0,
            }
        )

    thread = threading.Thread(target=run_price_archive_job, kwargs={"force": force}, daemon=True)
    thread.start()
    return True


def run_price_archive_job(*, force: bool = False) -> None:
    def on_status(updates: dict[str, Any]) -> None:
        update_price_archive_status(**updates)

    try:
        update_price_archive_status(running=True, phase="starting")
        result = archive_daily_prices(force=force, on_status=on_status)
        update_price_archive_status(
            running=False,
            phase="skipped" if result.get("skipped") else "done",
            finished_at=result.get("finished_at"),
            skipped=bool(result.get("skipped")),
            uuids_total=result.get("uuids_total", 0),
            uuids_found=result.get("uuids_found", 0),
            cards_processed=result.get("cards_processed", 0),
            cards_total=result.get("cards_total", 0),
            snapshots_written=result.get("snapshots_written", 0),
            last_archive_date=result.get("archive_date"),
            last_archive_finished_at=result.get("finished_at"),
            error=result.get("error"),
            message="Archivage deja fait aujourd'hui" if result.get("skipped") else "Archivage termine",
        )
    except Exception as error:  # noqa: BLE001 - background archive should capture failures.
        update_price_archive_status(
            running=False,
            phase="error",
            error=str(error),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            message=f"Erreur: {error}",
        )


def weekly_backup_status_payload() -> dict[str, Any]:
    from .weekly_backup import weekly_backup_status

    with WEEKLY_BACKUP_LOCK:
        status = dict(WEEKLY_BACKUP_STATUS)
    status["schedule"] = weekly_backup_status()
    return status


def update_weekly_backup_status(**updates: Any) -> None:
    with WEEKLY_BACKUP_LOCK:
        WEEKLY_BACKUP_STATUS.update(updates)


def start_weekly_backup_job(*, force: bool = False) -> bool:
    with WEEKLY_BACKUP_LOCK:
        if WEEKLY_BACKUP_STATUS["running"]:
            return False
        WEEKLY_BACKUP_STATUS.update(
            {
                "running": True,
                "phase": "starting",
                "message": "Demarrage backup hebdo...",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "finished_at": None,
                "error": None,
                "skipped": False,
            }
        )

    thread = threading.Thread(target=run_weekly_backup_job, kwargs={"force": force}, daemon=True)
    thread.start()
    return True


def run_weekly_backup_job(*, force: bool = False) -> None:
    from .weekly_backup import run_weekly_backup

    def on_log(message: str) -> None:
        update_weekly_backup_status(message=message, phase="running")

    try:
        update_weekly_backup_status(running=True, phase="running", message="Backup en cours...")
        result = run_weekly_backup(force=force, on_log=on_log)
        update_weekly_backup_status(
            running=False,
            phase="skipped" if result.get("skipped") else "done",
            finished_at=result.get("finished_at"),
            skipped=bool(result.get("skipped")),
            rows_incremental=result.get("rows_incremental", 0),
            rows_snapshot=result.get("rows_snapshot", 0),
            backup_size_gb=result.get("backup_size_gb"),
            error=result.get("error"),
            message="Backup deja fait cette semaine" if result.get("skipped") else "Backup hebdo termine",
        )
    except Exception as error:  # noqa: BLE001
        update_weekly_backup_status(
            running=False,
            phase="error",
            error=str(error),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            message=f"Erreur backup: {error}",
        )


def log_db_audit_warnings() -> None:
    from .db_audit import collect_db_audit

    try:
        audit = collect_db_audit()
        print(
            f"[db-audit] {audit['db_files']['main'].get('size_gb')} Go — {audit['overall_status']}",
            flush=True,
        )
        for warning in audit.get("warnings") or []:
            print(f"[db-audit] [{warning['level']}] {warning['message']}", flush=True)
    except Exception as error:  # noqa: BLE001
        print(f"[db-audit] impossible: {error}", flush=True)


def maybe_start_weekly_backup() -> None:
    from .weekly_backup import weekly_backup_status

    try:
        status = weekly_backup_status()
        if not status.get("due"):
            return
        if start_weekly_backup_job(force=False):
            print("[weekly-backup] demarrage automatique (>= 7 jours)", flush=True)
    except Exception as error:  # noqa: BLE001
        print(f"[weekly-backup] check ignore: {error}", flush=True)


def maybe_start_daily_price_archive() -> None:
    if os.environ.get("MTG_PWA_SKIP_AUTO_ARCHIVE", "").lower() in {"1", "true", "yes", "on"}:
        return

    def delayed_start() -> None:
        time.sleep(3)
        wait_for_startup_warmup_idle()
        with open_db() as conn:
            from .database import get_app_metadata
            from datetime import date

            last_date = get_app_metadata(conn, "last_price_archive_date")
            if last_date == date.today().isoformat():
                update_price_archive_status(
                    last_archive_date=last_date,
                    last_archive_finished_at=get_app_metadata(conn, "last_price_archive_finished_at"),
                    phase="idle",
                    message="Archivage deja effectue aujourd'hui",
                )
                return
        if start_price_archive_job(force=False):
            print("Archivage quotidien des prix MTGJSON demarre en arriere-plan.")

    threading.Thread(target=delayed_start, daemon=True).start()


def startup_warmup_status_payload() -> dict[str, Any]:
    with STARTUP_LOCK:
        return dict(STARTUP_STATUS)


def wait_for_startup_warmup_idle(*, max_wait_seconds: float = 900.0) -> None:
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        with STARTUP_LOCK:
            if not STARTUP_STATUS.get("running"):
                return
        time.sleep(1.0)


def update_startup_warmup_status(**updates: Any) -> None:
    with STARTUP_LOCK:
        STARTUP_STATUS.update(updates)


def start_startup_warmup_job(*, force: bool = False) -> bool:
    with STARTUP_LOCK:
        if STARTUP_STATUS["running"]:
            return False
        STARTUP_STATUS.update(
            {
                "running": True,
                "phase": "starting",
                "message": "Demarrage...",
                "progress": 2,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "finished_at": None,
                "skipped": False,
                "error": None,
            }
        )

    thread = threading.Thread(target=run_startup_warmup_job, kwargs={"force": force}, daemon=True)
    thread.start()
    return True


def run_startup_warmup_job(*, force: bool = False) -> None:
    from .startup_warmup import run_startup_warmup

    def on_status(updates: dict[str, Any]) -> None:
        update_startup_warmup_status(**updates)

    try:
        result = run_startup_warmup(force=force, on_status=on_status)
        update_startup_warmup_status(
            running=False,
            phase=result.get("phase") or "done",
            message=result.get("message"),
            progress=result.get("progress", 100),
            finished_at=result.get("finished_at"),
            skipped=bool(result.get("skipped")),
            error=result.get("error"),
            catalog_categories=result.get("catalog_categories", 0),
            owned_cards_total=result.get("owned_cards_total", 0),
            owned_cards_refreshed=result.get("owned_cards_refreshed", 0),
            snapshots_written=result.get("snapshots_written", 0),
            siblings_fetched=result.get("siblings_fetched", 0),
            decks_indexed=result.get("decks_indexed", 0),
            market_tracked_cards=result.get("market_tracked_cards", 0),
            market_ranges_warmed=result.get("market_ranges_warmed", 0),
        )
        if not result.get("skipped"):
            invalidate_collection_blocks_cache(skip_index=True)
    except Exception as error:  # noqa: BLE001 - background warmup should capture failures.
        update_startup_warmup_status(
            running=False,
            phase="error",
            message=f"Erreur: {error}",
            error=str(error),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


def finish_variant_summaries(
    conn,
    client: ScryfallClient | None,
    card: dict[str, Any],
) -> list[dict[str, Any]]:
    """Other Scryfall printings with the same set and collector number (e.g. foil vs non-foil EA)."""
    set_code = (card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").strip()
    current_id = card.get("id")
    if not set_code or not collector_number or not current_id:
        return []

    current_finishes = set(available_finishes_for_card(card))
    candidates: dict[str, dict[str, Any]] = {}

    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT raw_json
        FROM {cards_table}
        WHERE lower(set_code) = ? AND collector_number = ? AND scryfall_id != ?
        """,
        (set_code, collector_number, current_id),
    ).fetchall()
    for row in rows:
        other = json.loads(row["raw_json"])
        other_id = other.get("id")
        if other_id:
            candidates[other_id] = other

    if client is not None:
        try:
            for printing in client.cards_by_set_collector(set_code, collector_number):
                printing_id = printing.get("id")
                if printing_id and printing_id != current_id:
                    candidates[printing_id] = printing
            if candidates:
                save_cards(conn, list(candidates.values()))
        except ScryfallError:
            pass

    summaries: list[dict[str, Any]] = []
    for other in candidates.values():
        other_finishes = [finish for finish in other.get("finishes") or [] if finish in VALID_FINISHES]
        if not other_finishes:
            continue
        if not any(finish not in current_finishes for finish in other_finishes):
            continue
        primary_finish = other_finishes[0]
        summary = card_summary(conn, other, primary_finish)
        owned = collection_quantities_for_card(conn, summary["id"])
        summary["owned_quantity"] = int(owned.get(primary_finish, 0))
        summaries.append(summary)

    return sorted(
        summaries,
        key=lambda item: (
            FINISH_ORDER.index(item["display_finish"])
            if item["display_finish"] in FINISH_ORDER
            else len(FINISH_ORDER),
            item.get("lang") or "",
        ),
    )


VALID_HISTORY_LANG_MODES = frozenset({"merge", "fr", "en", "both"})


def parse_display_lang(query: dict[str, list[str]]) -> str:
    mode = one(query, "display_lang", "").strip().lower()
    if mode in VALID_DISPLAY_LANG_MODES:
        return mode
    mode = one(query, "history_lang", "merge").strip().lower()
    if mode == "both":
        return "merge"
    return mode if mode in VALID_DISPLAY_LANG_MODES else "merge"


def parse_history_lang(query: dict[str, list[str]]) -> str:
    mode = one(query, "history_lang", "merge").strip().lower()
    return mode if mode in VALID_HISTORY_LANG_MODES else "merge"


def language_sibling_ids(
    conn,
    card: dict[str, Any],
    client: ScryfallClient | None = None,
) -> dict[str, str]:
    set_code = str(card.get("set") or "").lower()
    collector_number = str(card.get("collector_number") or "").strip()
    current_lang = str(card.get("lang") or "en").lower()
    if not set_code or not collector_number:
        return {current_lang: card["id"]}

    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT scryfall_id, raw_json
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

    if client is None:
        return ids

    for lang in ("fr", "en"):
        if lang in ids:
            continue
        try:
            found = client.card_by_set_number_lang(set_code, collector_number, lang)
            save_card(conn, found)
            ids[lang] = found["id"]
            client.throttle()
        except ScryfallError:
            continue
    return ids


def merge_price_histories(
    fr_history: list[dict[str, Any]],
    en_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for point in en_history:
        key = (point["snapshot_date"], point["source"], point["currency"], point["finish"])
        merged[key] = {**point, "price_lang": "en"}
    for point in fr_history:
        key = (point["snapshot_date"], point["source"], point["currency"], point["finish"])
        merged[key] = {**point, "price_lang": "fr"}
    return sorted(merged.values(), key=lambda item: (item["snapshot_date"], item.get("collected_at") or ""))


def combine_both_price_histories(
    fr_history: list[dict[str, Any]],
    en_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tagged = [{**point, "price_lang": "fr"} for point in fr_history]
    tagged.extend({**point, "price_lang": "en"} for point in en_history)
    return sorted(
        tagged,
        key=lambda item: (
            item["snapshot_date"],
            item.get("price_lang") or "",
            item.get("collected_at") or "",
        ),
    )


def price_history_for_lang_mode(
    conn,
    card: dict[str, Any],
    finish: str,
    lang_mode: str,
    *,
    client: ScryfallClient | None = None,
) -> list[dict[str, Any]]:
    if lang_mode not in VALID_HISTORY_LANG_MODES:
        lang_mode = "merge"

    scryfall_id = card["id"]
    card_lang = str(card.get("lang") or "en").lower()

    if lang_mode in {"merge", "both"} and (not card.get("set") or not card.get("collector_number")):
        return [{**point, "price_lang": card_lang} for point in price_history(conn, scryfall_id, finish)]

    siblings = language_sibling_ids(conn, card, client)

    if lang_mode == "fr":
        target = siblings.get("fr", scryfall_id)
        point_lang = "fr" if target == siblings.get("fr") else card_lang
        return [{**point, "price_lang": point_lang} for point in price_history(conn, target, finish)]

    if lang_mode == "en":
        target = siblings.get("en", scryfall_id)
        point_lang = "en" if target == siblings.get("en") else card_lang
        return [{**point, "price_lang": point_lang} for point in price_history(conn, target, finish)]

    fr_id = siblings.get("fr")
    en_id = siblings.get("en")
    if fr_id and en_id and fr_id == en_id:
        return [{**point, "price_lang": card_lang} for point in price_history(conn, scryfall_id, finish)]

    fr_hist = price_history(conn, fr_id, finish) if fr_id else []
    en_hist = price_history(conn, en_id, finish) if en_id else []
    if not fr_hist and not en_hist:
        return [{**point, "price_lang": card_lang} for point in price_history(conn, scryfall_id, finish)]
    if not fr_hist:
        return [{**point, "price_lang": "en"} for point in en_hist]
    if not en_hist:
        return [{**point, "price_lang": "fr"} for point in fr_hist]
    if lang_mode == "both":
        return combine_both_price_histories(fr_hist, en_hist)
    return merge_price_histories(fr_hist, en_hist)


def other_printing_summaries(
    conn,
    client: ScryfallClient,
    card: dict[str, Any],
    finish: str,
    *,
    max_cards: int = 100,
) -> list[dict[str, Any]]:
    oracle_id = card.get("oracle_id")
    if not oracle_id:
        return []
    try:
        printings = client.cards_by_oracle_id(oracle_id, max_cards=max_cards + 1)
    except ScryfallError:
        return []
    if printings:
        save_cards(conn, printings)
    summaries: list[dict[str, Any]] = []
    for printing in printings:
        if printing.get("id") == card.get("id"):
            continue
        summary = card_summary(conn, printing, finish)
        owned = collection_quantities_for_card(conn, printing["id"])
        summary["owned_breakdown"] = owned
        summary["owned_quantity"] = sum(owned.values())
        summaries.append(summary)
        if len(summaries) >= max_cards:
            break
    return summaries


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
    sync_build_info()
    invalidate_collection_blocks_cache(skip_index=True)
    with open_db() as conn:
        from .database import get_app_metadata

        update_price_archive_status(
            last_archive_date=get_app_metadata(conn, "last_price_archive_date"),
            last_archive_finished_at=get_app_metadata(conn, "last_price_archive_finished_at"),
        )
    server = ThreadingHTTPServer((host, port), MvpRequestHandler)
    print(f"MTG PWA disponible sur http://{host}:{port}")
    print(f"Catalogue collection v{COLLECTION_CATALOG_VERSION} (Secret Lair, Universes Beyond)")
    print("Ctrl+C pour arreter le serveur.")
    maybe_start_daily_price_archive()
    log_db_audit_warnings()
    maybe_start_weekly_backup()
    server.serve_forever()
