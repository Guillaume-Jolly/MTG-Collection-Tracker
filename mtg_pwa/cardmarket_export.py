from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .database import (
    DEFAULT_DB_PATH,
    cardmarket_product_id_by_scryfall,
    catalog_table,
    connect,
    get_app_metadata,
    init_db,
    save_cardmarket_price_guide_daily,
    save_cardmarket_product_mappings,
    set_app_metadata,
    tracked_mtgjson_cards,
    tracked_mtgjson_set_codes,
    utc_now,
)
from .cardmarket_retention import compact_cardmarket_guide_history
from .local_cache import USER_AGENT, cache_root, cached_set_codes, load_set_json

StatusCallback = Callable[[dict[str, Any]], None] | None
LogCallback = Callable[[str], None] | None

PRICE_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
PRICE_GUIDE_CACHE_NAME = "price_guide_1.json"
MAX_CACHE_AGE_HOURS = 24
WRITE_BATCH_SIZE = 400

LAST_CARDMARKET_ARCHIVE_DATE_KEY = "last_cardmarket_archive_date"
LAST_CARDMARKET_ARCHIVE_FINISHED_KEY = "last_cardmarket_archive_finished_at"
LAST_CARDMARKET_MAP_REFRESH_KEY = "last_cardmarket_map_refresh_at"


def cardmarket_cache_dir() -> Path:
    return cache_root() / "cardmarket"


def price_guide_cache_path() -> Path:
    return cardmarket_cache_dir() / PRICE_GUIDE_CACHE_NAME


def _cache_age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 3600


def download_price_guide(*, force: bool = False, timeout: int = 180) -> Path:
    path = price_guide_cache_path()
    age = _cache_age_hours(path)
    if not force and age is not None and age < MAX_CACHE_AGE_HOURS:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(PRICE_GUIDE_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cardmarket price guide HTTP {error.code}: {details}") from error
    except URLError as error:
        raise RuntimeError(f"Cardmarket price guide request failed: {error.reason}") from error

    path.write_bytes(payload)
    return path


def load_price_guide(path: Path | None = None) -> dict[str, Any]:
    guide_path = path or price_guide_cache_path()
    if not guide_path.exists():
        raise FileNotFoundError(f"Price guide cache missing: {guide_path}")
    return json.loads(guide_path.read_text(encoding="utf-8"))


def price_guide_entry_to_row(
    entry: dict[str, Any],
    *,
    snapshot_date: str,
    guide_version: int | None,
    guide_created_at: str | None,
    collected_at: str,
) -> dict[str, Any]:
    return {
        "id_product": int(entry["idProduct"]),
        "snapshot_date": snapshot_date,
        "trend": entry.get("trend"),
        "low_price": entry.get("low"),
        "avg": entry.get("avg"),
        "avg1": entry.get("avg1"),
        "avg7": entry.get("avg7"),
        "avg30": entry.get("avg30"),
        "trend_foil": entry.get("trend-foil"),
        "low_foil": entry.get("low-foil"),
        "avg_foil": entry.get("avg-foil"),
        "avg1_foil": entry.get("avg1-foil"),
        "avg7_foil": entry.get("avg7-foil"),
        "avg30_foil": entry.get("avg30-foil"),
        "guide_version": guide_version,
        "guide_created_at": guide_created_at,
        "collected_at": collected_at,
    }


def build_product_mappings_for_set(set_code: str) -> list[dict[str, Any]]:
    payload = load_set_json(set_code.upper())
    set_code_value = (payload.get("code") or set_code).upper()
    mappings: list[dict[str, Any]] = []
    for card in payload.get("cards") or []:
        identifiers = card.get("identifiers") or {}
        scryfall_id = identifiers.get("scryfallId")
        id_product = identifiers.get("mcmId")
        if not scryfall_id or id_product is None:
            continue
        mappings.append(
            {
                "id_product": int(id_product),
                "scryfall_id": scryfall_id,
                "set_code": set_code_value,
                "collector_number": card.get("number"),
            }
        )
    return mappings


def refresh_cardmarket_product_map(
    conn,
    *,
    set_codes: list[str] | None = None,
    on_log: LogCallback = None,
) -> int:
    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)
        else:
            print(message, flush=True)

    codes = set_codes or cached_set_codes() or tracked_mtgjson_set_codes(conn)
    if not codes:
        log("Aucun set MTGJSON en cache pour le mapping Cardmarket.")
        return 0

    total_written = 0
    for set_code in codes:
        try:
            mappings = build_product_mappings_for_set(set_code)
        except Exception as error:  # noqa: BLE001 - continue other sets on failure
            log(f"Mapping Cardmarket ignore pour {set_code}: {error}")
            continue
        if mappings:
            total_written += save_cardmarket_product_mappings(conn, mappings)
            conn.commit()
    set_app_metadata(conn, LAST_CARDMARKET_MAP_REFRESH_KEY, utc_now())
    conn.commit()
    log(f"Mapping Cardmarket mis a jour: {total_written} produits sur {len(codes)} sets.")
    return total_written


def cardmarket_archive_already_done_today(conn, *, force: bool) -> bool:
    if force:
        return False
    last_date = get_app_metadata(conn, LAST_CARDMARKET_ARCHIVE_DATE_KEY)
    return last_date == date.today().isoformat()


def archive_daily_cardmarket_prices(
    *,
    db_path: str | None = None,
    force: bool = False,
    on_status: StatusCallback = None,
    on_log: LogCallback = None,
) -> dict[str, Any]:
    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)
        else:
            print(message, flush=True)

    def status(**updates: Any) -> None:
        if on_status is not None:
            on_status(updates)

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    archive_date = date.today().isoformat()
    result: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": None,
        "archive_date": archive_date,
        "error": None,
        "skipped": False,
        "products_mapped": 0,
        "products_tracked": 0,
        "rows_written": 0,
        "phase": "idle",
    }

    db = connect(db_path or DEFAULT_DB_PATH)
    init_db(db)

    try:
        if cardmarket_archive_already_done_today(db, force=force):
            result["skipped"] = True
            result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            result["phase"] = "skipped"
            status(
                running=False,
                cardmarket_phase="skipped",
                cardmarket_skipped=True,
                cardmarket_finished_at=result["finished_at"],
                message="Archivage Cardmarket deja effectue aujourd'hui",
            )
            log(f"Archivage Cardmarket deja effectue aujourd'hui ({archive_date}).")
            return result

        status(cardmarket_phase="mapping", message="Mise a jour du mapping Cardmarket...")
        log("Mise a jour du mapping idProduct -> scryfall_id depuis les sets MTGJSON en cache...")
        result["products_mapped"] = refresh_cardmarket_product_map(db, on_log=on_log)

        map_table = catalog_table("cardmarket_product_map")
        tracked_products = {
            int(row["id_product"])
            for row in db.execute(f"SELECT id_product FROM {map_table}").fetchall()
        }
        result["products_tracked"] = len(tracked_products)
        if not tracked_products:
            raise ValueError("Aucun idProduct Cardmarket mappe. Verifiez le cache MTGJSON sets.")

        status(cardmarket_phase="downloading", message="Telechargement du price guide Cardmarket...")
        log("Telechargement du price guide Cardmarket (fichier ~25 Mo)...")
        guide_path = download_price_guide(force=force)
        guide = load_price_guide(guide_path)
        guide_version = guide.get("version")
        guide_created_at = guide.get("createdAt")
        collected_at = utc_now()

        status(
            cardmarket_phase="writing",
            cardmarket_products_tracked=len(tracked_products),
            message=f"Ecriture Cardmarket: 0/{len(tracked_products)} produits",
        )
        log(f"Price guide charge ({len(guide.get('priceGuides') or [])} produits totaux).")

        rows_written = 0
        pending_rows: list[dict[str, Any]] = []

        def flush_rows() -> None:
            nonlocal rows_written, pending_rows
            if not pending_rows:
                return
            rows_written += save_cardmarket_price_guide_daily(db, pending_rows)
            db.commit()
            pending_rows = []

        for entry in guide.get("priceGuides") or []:
            id_product = entry.get("idProduct")
            if id_product is None or int(id_product) not in tracked_products:
                continue
            pending_rows.append(
                price_guide_entry_to_row(
                    entry,
                    snapshot_date=archive_date,
                    guide_version=guide_version,
                    guide_created_at=guide_created_at,
                    collected_at=collected_at,
                )
            )
            if len(pending_rows) >= WRITE_BATCH_SIZE:
                flush_rows()
                status(
                    cardmarket_phase="writing",
                    cardmarket_rows_written=rows_written + len(pending_rows),
                    cardmarket_products_tracked=len(tracked_products),
                    message=f"Ecriture Cardmarket: {rows_written + len(pending_rows)}/{len(tracked_products)} produits",
                )

        flush_rows()
        retention = compact_cardmarket_guide_history(db)
        result["retention"] = retention
        set_app_metadata(db, LAST_CARDMARKET_ARCHIVE_DATE_KEY, archive_date)
        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        set_app_metadata(db, LAST_CARDMARKET_ARCHIVE_FINISHED_KEY, finished_at)
        db.commit()

        result["rows_written"] = rows_written
        result["finished_at"] = finished_at
        result["phase"] = "done"
        status(
            running=False,
            cardmarket_phase="done",
            cardmarket_skipped=False,
            cardmarket_rows_written=rows_written,
            cardmarket_products_tracked=len(tracked_products),
            cardmarket_products_mapped=result["products_mapped"],
            cardmarket_finished_at=finished_at,
            last_cardmarket_archive_date=archive_date,
            last_cardmarket_archive_finished_at=finished_at,
            message="Archivage Cardmarket termine",
        )
        log(
            f"Archivage Cardmarket termine: {rows_written} lignes pour "
            f"{len(tracked_products)} produits suivis ({archive_date})."
        )
        return result
    except Exception as error:  # noqa: BLE001 - archive should report failures to caller.
        result["error"] = str(error)
        result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["phase"] = "error"
        status(
            running=False,
            cardmarket_phase="error",
            cardmarket_error=str(error),
            cardmarket_finished_at=result["finished_at"],
            message=f"Erreur Cardmarket: {error}",
        )
        raise
    finally:
        db.close()


def cardmarket_product_url(id_product: int, *, foil: bool = False) -> str:
    url = f"https://www.cardmarket.com/en/Magic/Products?idProduct={int(id_product)}"
    if foil:
        url += "&isFoil=Y"
    return url


CARDMARKET_WANTS_URL = "https://www.cardmarket.com/en/Magic/Wants/Lists"
CARDMARKET_SHOPPING_WIZARD_URL = "https://www.cardmarket.com/en/Magic/Wants/ShoppingWizard"


def build_wants_decklist_line(*, quantity: int, name: str, set_name: str) -> str:
    clean_name = (name or "").strip()
    clean_set = (set_name or "").strip()
    if quantity <= 1:
        return f"1 {clean_name} ({clean_set})"
    return f"{quantity}x {clean_name} ({clean_set})"


def build_cardmarket_order_plan(
    conn,
    items: list[dict[str, Any]],
    *,
    finish: str = "nonfoil",
    playset: bool = False,
    display_lang: str = "merge",
) -> dict[str, Any]:
    from .database import batch_cardmarket_latest_guide, cardmarket_product_id_by_scryfall

    scryfall_ids = [item["scryfall_id"] for item in items if item.get("scryfall_id")]
    product_map = cardmarket_product_id_by_scryfall(conn, scryfall_ids)
    guides_by_id: dict[str, dict[str, Any]] = {}
    items_by_finish: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        item_finish = str(item.get("finish") or finish).strip().lower()
        if item_finish not in {"nonfoil", "foil", "etched"}:
            item_finish = finish
        items_by_finish.setdefault(item_finish, []).append(item)
    for item_finish, finish_items in items_by_finish.items():
        finish_ids = [entry["scryfall_id"] for entry in finish_items if entry.get("scryfall_id")]
        guides_by_id.update(batch_cardmarket_latest_guide(conn, finish_ids, finish=item_finish))
    decklist_lines: list[str] = []
    products: list[dict[str, Any]] = []
    missing_map: list[str] = []
    estimated_subtotal = 0.0
    priced_lines = 0
    qty_multiplier = 4 if playset else 1

    for item in items:
        scryfall_id = item.get("scryfall_id")
        if not scryfall_id:
            continue
        quantity = max(1, int(item.get("quantity") or 1)) * qty_multiplier
        name = item.get("name") or scryfall_id
        if display_lang == "fr" and item.get("printed_name"):
            name = item["printed_name"]
        set_name = item.get("set_name") or item.get("set_code") or ""
        decklist_lines.append(build_wants_decklist_line(quantity=quantity, name=name, set_name=set_name))
        id_product = product_map.get(scryfall_id)
        if id_product is None:
            missing_map.append(scryfall_id)
            continue
        item_finish = str(item.get("finish") or finish).strip().lower()
        if item_finish not in {"nonfoil", "foil", "etched"}:
            item_finish = finish
        guide = guides_by_id.get(scryfall_id)
        trend = None
        if guide and guide.get("metrics"):
            trend = guide["metrics"].get("trend")
        if trend is not None:
            estimated_subtotal += float(trend) * quantity
            priced_lines += quantity
        products.append(
            {
                "scryfall_id": scryfall_id,
                "id_product": id_product,
                "name": name,
                "set_name": set_name,
                "quantity": quantity,
                "finish": item_finish,
                "product_url": cardmarket_product_url(id_product, foil=item_finish == "foil"),
                "trend": trend,
            }
        )

    return {
        "decklist_text": "\n".join(decklist_lines),
        "wants_url": CARDMARKET_WANTS_URL,
        "shopping_wizard_url": CARDMARKET_SHOPPING_WIZARD_URL,
        "products": products,
        "lines_total": len(decklist_lines),
        "products_mapped": len(products),
        "missing_product_map": missing_map,
        "estimated_subtotal_trend": round(estimated_subtotal, 2),
        "priced_lines": priced_lines,
        "currency": "EUR",
        "playset": playset,
        "display_lang": display_lang,
        "note": (
            "Cardmarket ne propose pas de lien public pour remplir le panier avec frais de port. "
            "Copiez la decklist dans Buying > My Wants > Add Decklist, puis ouvrez le Shopping Wizard "
            "pour obtenir le total avec livraison."
        ),
    }
