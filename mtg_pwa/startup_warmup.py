from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .database import (
    catalog_table,
    connect,
    get_app_metadata,
    get_cached_card,
    init_db,
    language_sibling_ids_db,
    save_card,
    save_cards,
    save_price_snapshots,
    set_app_metadata,
)
from .local_cache import load_deck_list
from .prices import available_finishes_for_card
from .scryfall import ScryfallClient, ScryfallError
from .sets_catalog import blocks_catalog, enrich_blocks_with_collection, owned_scryfall_ids

StatusCallback = Callable[[dict[str, Any]], None] | None

LAST_WARMUP_KEY = "last_startup_warmup_at"
WARMUP_MIN_INTERVAL_HOURS = 6
WARMUP_PHASE_PAUSE_SECONDS = 0.5
MTGJSON_SYNC_BATCH_SIZE = 20
MTGJSON_SYNC_BATCH_PAUSE_SECONDS = 0.25


def warmup_recently_done(conn, *, min_hours: int = WARMUP_MIN_INTERVAL_HOURS) -> bool:
    raw = get_app_metadata(conn, LAST_WARMUP_KEY)
    if not raw:
        return False
    try:
        finished = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - finished < timedelta(hours=min_hours)


def warm_collection_catalog(conn) -> dict[str, int]:
    payload = {"categories": enrich_blocks_with_collection(blocks_catalog())}
    return {"categories": len(payload.get("categories") or [])}


def refresh_owned_prices(
    conn,
    client: ScryfallClient,
    *,
    batch_size: int = 40,
    on_progress: StatusCallback = None,
) -> dict[str, int]:
    from .price_sync import card_price_sync_plan
    from .server import ensure_price_fallback, sync_mtgjson_for_card

    scryfall_ids = owned_scryfall_ids(conn)
    total = len(scryfall_ids)
    refreshed = 0
    skipped = 0
    snapshots = 0
    errors = 0

    scryfall_fetch_ids: list[str] = []
    mtgjson_only_ids: list[str] = []

    for scryfall_id in scryfall_ids:
        plan = card_price_sync_plan(conn, scryfall_id)
        if plan["skip"]:
            skipped += 1
            continue
        if plan["needs_scryfall"] or plan["needs_fallback"]:
            scryfall_fetch_ids.append(scryfall_id)
        elif plan["needs_mtgjson"]:
            mtgjson_only_ids.append(scryfall_id)

    processed = skipped

    for offset in range(0, len(scryfall_fetch_ids), batch_size):
        batch = scryfall_fetch_ids[offset : offset + batch_size]
        if not batch:
            break
        try:
            cards = client.collection(batch)
            save_cards(conn, cards)
            for card in cards:
                snapshots += save_price_snapshots(conn, card)
                for finish in available_finishes_for_card(card):
                    snapshots += ensure_price_fallback(conn, client, card, finish)
                snapshots += sync_mtgjson_for_card(conn, card)
            refreshed += len(cards)
            client.throttle()
            conn.commit()
        except ScryfallError:
            errors += len(batch)
        processed = skipped + min(offset + len(batch), len(scryfall_fetch_ids))
        if on_progress:
            on_progress(
                {
                    "cards_processed": processed,
                    "cards_total": total,
                    "cards_skipped": skipped,
                }
            )

    for scryfall_id in mtgjson_only_ids:
        card = get_cached_card(conn, scryfall_id)
        if not card:
            continue
        snapshots += sync_mtgjson_for_card(conn, card)
        refreshed += 1
        processed += 1
        if processed % MTGJSON_SYNC_BATCH_SIZE == 0:
            conn.commit()
            time.sleep(MTGJSON_SYNC_BATCH_PAUSE_SECONDS)
        if on_progress and (processed == skipped + 1 or processed % 20 == 0 or processed == total):
            on_progress(
                {
                    "cards_processed": processed,
                    "cards_total": total,
                    "cards_skipped": skipped,
                }
            )
    conn.commit()

    if on_progress:
        on_progress(
            {
                "cards_processed": total,
                "cards_total": total,
                "cards_skipped": skipped,
            }
        )

    return {
        "cards_total": total,
        "cards_refreshed": refreshed,
        "cards_skipped": skipped,
        "snapshots_written": snapshots,
        "errors": errors,
    }


def warm_owned_language_siblings(
    conn,
    client: ScryfallClient,
    *,
    limit: int = 48,
) -> dict[str, int]:
    cards_table = catalog_table("cards")
    rows = conn.execute(
        f"""
        SELECT DISTINCT c.raw_json
        FROM collection_items ci
        JOIN {cards_table} c ON c.scryfall_id = ci.scryfall_id
        WHERE ci.quantity > 0
        LIMIT ?
        """,
        (max(limit * 2, limit),),
    ).fetchall()

    fetched = 0
    checked = 0
    for row in rows:
        if fetched >= limit:
            break
        card = json.loads(row["raw_json"])
        set_code = card.get("set")
        collector_number = card.get("collector_number")
        if not set_code or not collector_number:
            continue
        checked += 1
        siblings = language_sibling_ids_db(conn, card)
        for lang in ("fr", "en"):
            if lang in siblings:
                continue
            try:
                found = client.card_by_set_number_lang(set_code, collector_number, lang)
                save_card(conn, found)
                client.throttle()
                fetched += 1
                if fetched >= limit:
                    break
            except ScryfallError:
                continue
    conn.commit()
    return {"checked": checked, "siblings_fetched": fetched}


def warm_deck_index() -> dict[str, int]:
    decks = load_deck_list()
    return {"decks_indexed": len(decks or [])}


def warm_market_tab(
    conn,
    *,
    on_progress: StatusCallback = None,
) -> dict[str, int]:
    from .server import warm_market_movers_cache

    return warm_market_movers_cache(conn, on_progress=on_progress)


def pause_between_warmup_phases() -> None:
    if WARMUP_PHASE_PAUSE_SECONDS > 0:
        time.sleep(WARMUP_PHASE_PAUSE_SECONDS)


def run_startup_warmup(
    *,
    force: bool = False,
    on_status: StatusCallback = None,
) -> dict[str, Any]:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": None,
        "skipped": False,
        "error": None,
        "phase": "done",
        "message": "Pret",
        "progress": 100,
        "catalog_categories": 0,
        "owned_cards_total": 0,
        "owned_cards_refreshed": 0,
        "owned_cards_skipped": 0,
        "snapshots_written": 0,
        "siblings_fetched": 0,
        "decks_indexed": 0,
        "market_tracked_cards": 0,
        "market_ranges_warmed": 0,
    }

    def status(**updates: Any) -> None:
        if on_status:
            on_status(updates)

    try:
        conn = connect()
        init_db(conn)
        try:
            skip_heavy = not force and warmup_recently_done(conn)
        finally:
            conn.close()

        status(running=True, phase="starting", message="Demarrage...", progress=3)
        client = ScryfallClient()

        if not skip_heavy:
            status(phase="catalog", message="Index des extensions...", progress=8)
            conn = connect()
            init_db(conn)
            try:
                catalog_stats = warm_collection_catalog(conn)
                result["catalog_categories"] = catalog_stats["categories"]
                conn.commit()
            finally:
                conn.close()
            pause_between_warmup_phases()

        price_progress_start = 12 if skip_heavy else 18
        price_progress_span = 48 if skip_heavy else 42
        status(
            phase="owned_prices",
            message="Prix en cours de chargement...",
            progress=price_progress_start,
            skipped=skip_heavy,
        )
        conn = connect()
        init_db(conn)
        try:

            def owned_progress(updates: dict[str, Any]) -> None:
                total = max(updates.get("cards_total") or 1, 1)
                done = updates.get("cards_processed") or 0
                skipped_cards = updates.get("cards_skipped") or 0
                progress = price_progress_start + int((done / total) * price_progress_span)
                if done >= total and skipped_cards == total:
                    message = "Prix deja a jour (donnees locales)"
                elif skipped_cards:
                    message = f"Prix en cours de chargement... {done}/{total}"
                else:
                    message = f"Prix en cours de chargement... {done}/{total}"
                status(
                    phase="owned_prices",
                    message=message,
                    progress=progress,
                    cards_processed=done,
                    cards_total=total,
                    cards_skipped=skipped_cards,
                    skipped=skip_heavy,
                )

            owned_stats = refresh_owned_prices(conn, client, on_progress=owned_progress)
            result.update(
                {
                    "owned_cards_total": owned_stats["cards_total"],
                    "owned_cards_refreshed": owned_stats["cards_refreshed"],
                    "owned_cards_skipped": owned_stats.get("cards_skipped", 0),
                    "snapshots_written": owned_stats["snapshots_written"],
                }
            )
        finally:
            conn.close()
        pause_between_warmup_phases()

        if not skip_heavy:
            status(phase="siblings", message="Impressions FR / EN...", progress=62, skipped=False)
            conn = connect()
            init_db(conn)
            try:
                sibling_stats = warm_owned_language_siblings(conn, client)
                result["siblings_fetched"] = sibling_stats["siblings_fetched"]
            finally:
                conn.close()
            pause_between_warmup_phases()

            status(phase="decks", message="Index des decks Commander...", progress=68, skipped=False)
            deck_stats = warm_deck_index()
            result["decks_indexed"] = deck_stats["decks_indexed"]
            pause_between_warmup_phases()

        market_progress_start = 62 if skip_heavy else 72
        status(
            phase="market",
            message="Prix du marche en cours de chargement...",
            progress=market_progress_start,
            skipped=skip_heavy,
        )
        conn = connect()
        init_db(conn)
        try:

            def market_progress(updates: dict[str, Any]) -> None:
                ranges_total = max(updates.get("ranges_total") or 1, 1)
                range_index = updates.get("range_index") or 1
                range_key = updates.get("range") or ""
                progress = market_progress_start + int((range_index / ranges_total) * 24)
                status(
                    phase="market",
                    message=f"Prix du marche en cours de chargement ({range_key})...",
                    progress=progress,
                    market_range=range_key,
                    market_range_index=range_index,
                    market_ranges_total=ranges_total,
                    skipped=skip_heavy,
                )

            market_stats = warm_market_tab(conn, on_progress=market_progress)
            result.update(
                {
                    "market_tracked_cards": market_stats["tracked_cards"],
                    "market_ranges_warmed": market_stats["ranges_warmed"],
                }
            )
        finally:
            conn.close()

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not skip_heavy:
            conn = connect()
            init_db(conn)
            try:
                set_app_metadata(conn, LAST_WARMUP_KEY, finished_at)
                conn.commit()
            finally:
                conn.close()

        result.update(
            {
                "skipped": skip_heavy,
                "finished_at": finished_at,
                "phase": "done",
                "message": "Chargement termine",
                "progress": 100,
            }
        )
        status(**result, running=False)
        return result
    except Exception as error:  # noqa: BLE001 - warmup reports failures to caller.
        result.update(
            {
                "error": str(error),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "phase": "error",
                "message": f"Erreur: {error}",
            }
        )
        status(**result, running=False)
        return result
