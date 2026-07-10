from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

from .cardmarket_export import archive_daily_cardmarket_prices
from .database import DEFAULT_DB_PATH, connect, init_db

StatusCallback = Callable[[dict[str, Any]], None] | None
LogCallback = Callable[[str], None] | None


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

    try:
        log("Archivage MTGJSON ignore: suivi EUR / Cardmarket uniquement.")
        result["snapshots_written"] = 0
        result["cards_processed"] = 0
        result["uuids_found"] = 0
        result["uuids_total"] = 0
        result["cards_total"] = 0

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
        result["skipped"] = result["cardmarket_skipped"]

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
                f"Archivage termine: Cardmarket {result['cardmarket_rows_written']} lignes "
                f"({result['archive_date']})."
            )
        from .price_daily import sync_price_daily_metadata

        sync_price_daily_metadata(db)
        if not result["cardmarket_skipped"]:
            db.execute("DELETE FROM app_metadata WHERE key LIKE 'market_movers_cache:%'")
            db.commit()
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
