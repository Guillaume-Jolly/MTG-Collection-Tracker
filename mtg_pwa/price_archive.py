from __future__ import annotations

import copy
import time
from datetime import date
from typing import Any, Callable

from .cardmarket_export import archive_daily_cardmarket_prices
from .database import (
    DEFAULT_DB_PATH,
    cached_mtgjson_price_entry,
    connect,
    get_app_metadata,
    init_db,
    save_external_price_snapshots,
    save_mtgjson_price_entry,
    set_app_metadata,
    tracked_mtgjson_cards,
)
from .mtgjson import extract_price_entries_today, normalize_price_points

StatusCallback = Callable[[dict[str, Any]], None] | None
LogCallback = Callable[[str], None] | None

LAST_ARCHIVE_DATE_KEY = "last_price_archive_date"
LAST_ARCHIVE_FINISHED_KEY = "last_price_archive_finished_at"
WRITE_BATCH_SIZE = 400


def merge_mtgjson_price_entries(existing: dict[str, Any] | None, today: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return copy.deepcopy(today)
    merged = copy.deepcopy(existing)
    for provider, today_provider in (today.get("paper") or {}).items():
        merged_provider = merged.setdefault("paper", {}).setdefault(provider, {})
        if today_provider.get("currency"):
            merged_provider["currency"] = today_provider["currency"]
        today_retail = today_provider.get("retail") or {}
        merged_retail = merged_provider.setdefault("retail", {})
        for finish, today_prices in today_retail.items():
            if not isinstance(today_prices, dict):
                continue
            merged_finish = merged_retail.setdefault(finish, {})
            merged_finish.update(today_prices)
    return merged


def archive_already_done_today(conn, *, force: bool) -> bool:
    if force:
        return False
    last_date = get_app_metadata(conn, LAST_ARCHIVE_DATE_KEY)
    return last_date == date.today().isoformat()


def archive_daily_prices(
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
    result: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": None,
        "archive_date": date.today().isoformat(),
        "error": None,
        "skipped": False,
        "uuids_total": 0,
        "uuids_found": 0,
        "cards_processed": 0,
        "cards_total": 0,
        "snapshots_written": 0,
        "cardmarket_skipped": False,
        "cardmarket_rows_written": 0,
        "cardmarket_products_tracked": 0,
        "phase": "idle",
    }

    db = connect(db_path or DEFAULT_DB_PATH)
    init_db(db)
    mtgjson_skipped = False

    try:
        if archive_already_done_today(db, force=force):
            mtgjson_skipped = True
            log(f"Archivage MTGJSON deja effectue aujourd'hui ({result['archive_date']}).")
        else:
            tracked = tracked_mtgjson_cards(db)
            if not tracked:
                raise ValueError(
                    "Aucune carte MTGJSON suivie. Lancez preload_strixhaven_prices.py ou importez des decks."
                )

            uuid_by_scryfall = {card["mtgjson_uuid"]: card["scryfall_id"] for card in tracked}
            uuids = list(uuid_by_scryfall)
            result["uuids_total"] = len(uuids)
            result["cards_total"] = len(uuids)
            status(
                phase="preparing",
                uuids_total=len(uuids),
                cards_total=len(uuids),
                cards_processed=0,
                uuids_found=0,
                snapshots_written=0,
            )
            log(f"Archivage quotidien: {len(uuids)} cartes suivies dans mtgjson_card_map.")

            status(phase="downloading", message="Telechargement MTGJSON AllPricesToday...")
            log("Telechargement MTGJSON AllPricesToday (fichier volumineux, patience)...")

            def on_parse_progress(found: int, total: int) -> None:
                status(
                    phase="parsing",
                    uuids_found=found,
                    uuids_total=total,
                    message=f"Lecture des prix du jour: {found}/{total} cartes trouvees",
                )

            entries = extract_price_entries_today(uuids, on_progress=on_parse_progress)
            result["uuids_found"] = len(entries)
            status(
                phase="writing",
                uuids_found=len(entries),
                message=f"Ecriture en base: 0/{len(entries)} cartes",
            )
            log(f"Prix du jour recuperes pour {len(entries)}/{len(uuids)} cartes.")

            snapshots_written = 0
            cards_processed = 0
            pending_points: list[dict[str, Any]] = []

            def flush_points() -> None:
                nonlocal snapshots_written, pending_points
                if not pending_points:
                    return
                snapshots_written += save_external_price_snapshots(db, pending_points)
                db.commit()
                pending_points = []

            for uuid, entry in entries.items():
                scryfall_id = uuid_by_scryfall.get(uuid)
                if not scryfall_id:
                    continue
                cached = cached_mtgjson_price_entry(db, uuid)
                merged = merge_mtgjson_price_entries(cached, entry)
                save_mtgjson_price_entry(db, uuid, merged)
                pending_points.extend(normalize_price_points(scryfall_id, entry))
                cards_processed += 1
                if len(pending_points) >= WRITE_BATCH_SIZE:
                    flush_points()
                if cards_processed == 1 or cards_processed % 500 == 0 or cards_processed == len(entries):
                    status(
                        phase="writing",
                        cards_processed=cards_processed,
                        cards_total=len(entries),
                        uuids_found=len(entries),
                        snapshots_written=snapshots_written + len(pending_points),
                        message=f"Ecriture en base: {cards_processed}/{len(entries)} cartes",
                    )
                    log(f"Ecriture: {cards_processed}/{len(entries)} cartes")

            flush_points()
            set_app_metadata(db, LAST_ARCHIVE_DATE_KEY, result["archive_date"])
            mtgjson_finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            set_app_metadata(db, LAST_ARCHIVE_FINISHED_KEY, mtgjson_finished_at)

            result["cards_processed"] = cards_processed
            result["snapshots_written"] = snapshots_written
            log(
                f"Archivage MTGJSON termine: {snapshots_written} snapshots ecrits pour "
                f"{cards_processed} cartes ({result['archive_date']})."
            )

        status(phase="cardmarket", message="Archivage Cardmarket...")
        log("Archivage Cardmarket (price guide quotidien)...")
        cardmarket_result = archive_daily_cardmarket_prices(
            db_path=db_path,
            force=force,
            on_status=on_status,
            on_log=on_log,
        )
        result["cardmarket_skipped"] = bool(cardmarket_result.get("skipped"))
        result["cardmarket_rows_written"] = int(cardmarket_result.get("rows_written") or 0)
        result["cardmarket_products_tracked"] = int(cardmarket_result.get("products_tracked") or 0)
        result["skipped"] = mtgjson_skipped and result["cardmarket_skipped"]

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["finished_at"] = finished_at
        result["phase"] = "skipped" if result["skipped"] else "done"
        status(
            running=False,
            phase=result["phase"],
            finished_at=finished_at,
            skipped=result["skipped"],
            cards_processed=result["cards_processed"],
            cards_total=result["cards_total"],
            uuids_found=result["uuids_found"],
            uuids_total=result["uuids_total"],
            snapshots_written=result["snapshots_written"],
            cardmarket_skipped=result["cardmarket_skipped"],
            cardmarket_rows_written=result["cardmarket_rows_written"],
            cardmarket_products_tracked=result["cardmarket_products_tracked"],
            last_archive_date=result["archive_date"],
            last_archive_finished_at=finished_at,
            message="Archivage deja fait aujourd'hui" if result["skipped"] else "Archivage termine",
        )
        if result["skipped"]:
            log(f"Archivage deja effectue aujourd'hui ({result['archive_date']}).")
        else:
            log(
                f"Archivage termine: MTGJSON {result['snapshots_written']} snapshots, "
                f"Cardmarket {result['cardmarket_rows_written']} lignes ({result['archive_date']})."
            )
        return result
    except Exception as error:  # noqa: BLE001 - archive should report failures to caller.
        result["error"] = str(error)
        result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["phase"] = "error"
        status(
            running=False,
            phase="error",
            error=str(error),
            finished_at=result["finished_at"],
            message=f"Erreur: {error}",
        )
        raise
    finally:
        db.close()
