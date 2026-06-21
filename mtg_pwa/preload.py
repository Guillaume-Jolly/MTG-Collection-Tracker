from __future__ import annotations

import json
import time
from typing import Any, Callable

from .database import (
    DEFAULT_DB_PATH,
    connect,
    image_url_for,
    init_db,
    large_image_url_for,
    save_cards,
    save_external_price_snapshots,
    save_mtgjson_price_entry,
    save_mtgjson_uuid,
    cached_mtgjson_price_entry,
)
from .local_cache import download_image, load_deck, load_deck_list
from .mtgjson import extract_price_entries, importable_deck_cards, normalize_price_points, search_decks
from .scryfall import ScryfallClient


StatusCallback = Callable[[dict[str, Any]], None] | None


def preload_commander_decks(
    *,
    limit: int | None = None,
    commander_only: bool = True,
    download_images: bool = True,
    db_path: str | None = None,
    on_status: StatusCallback = None,
    on_log: Callable[[str], None] | None = None,
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
        "error": None,
        "decks_total": 0,
        "decks_processed": 0,
        "decks_cached": 0,
        "unique_uuids": 0,
        "cached_uuids": 0,
        "fetched_uuids": 0,
        "missing_uuids": 0,
        "scryfall_cards_cached": 0,
        "images_downloaded": 0,
        "images_skipped": 0,
        "images_failed": 0,
        "points": 0,
        "snapshots_written": 0,
    }

    try:
        log("Chargement de la liste des decks MTGJSON...")
        load_deck_list()

        decks, _ = search_decks("", limit=limit or 10000, commander_only=commander_only)
        if limit is not None:
            decks = decks[:limit]
        result["decks_total"] = len(decks)
        status(decks_total=len(decks))
        log(f"{len(decks)} deck(s) Commander a precharger.")

        deck_cards: list[dict[str, Any]] = []
        for index, deck in enumerate(decks, start=1):
            deck_payload = load_deck(deck["file_name"])
            result["decks_cached"] += 1
            deck_cards.extend(importable_deck_cards(deck_payload))
            result["decks_processed"] = index
            status(decks_processed=index)
            if index == 1 or index % 10 == 0 or index == len(decks):
                log(f"Decks MTGJSON: {index}/{len(decks)}")

        unique_by_uuid = {
            card["mtgjson_uuid"]: card
            for card in deck_cards
            if card.get("mtgjson_uuid") and card.get("scryfall_id")
        }
        result["unique_uuids"] = len(unique_by_uuid)
        status(unique_uuids=len(unique_by_uuid))
        log(f"{len(unique_by_uuid)} cartes uniques (UUID MTGJSON).")

        db = connect(db_path or DEFAULT_DB_PATH)
        init_db(db)

        missing_uuids: list[str] = []
        entries: dict[str, dict[str, Any]] = {}
        for uuid, deck_card in unique_by_uuid.items():
            save_mtgjson_uuid(
                db,
                scryfall_id=deck_card["scryfall_id"],
                mtgjson_uuid=uuid,
                set_code=deck_card["set_code"],
                collector_number=deck_card["collector_number"],
            )
            cached = cached_mtgjson_price_entry(db, uuid)
            if cached is None:
                missing_uuids.append(uuid)
            else:
                entries[uuid] = cached

        result["cached_uuids"] = len(entries)
        status(cached_uuids=len(entries))
        log(f"Prix MTGJSON deja en cache: {len(entries)}, a telecharger: {len(missing_uuids)}")

        if missing_uuids:
            log("Telechargement des prix MTGJSON AllPrices (peut prendre plusieurs minutes)...")
            fetched_entries = extract_price_entries(missing_uuids)
            result["fetched_uuids"] = len(fetched_entries)
            result["missing_uuids"] = len(set(missing_uuids) - set(fetched_entries))
            status(
                fetched_uuids=len(fetched_entries),
                missing_uuids=result["missing_uuids"],
            )
            log(
                f"Prix MTGJSON recuperes: {len(fetched_entries)}, "
                f"manquants: {result['missing_uuids']}"
            )
        else:
            fetched_entries = {}

        scryfall_ids = sorted({card["scryfall_id"] for card in unique_by_uuid.values()})
        client = ScryfallClient()
        log(f"Telechargement des cartes Scryfall: {len(scryfall_ids)} identifiants...")
        for index in range(0, len(scryfall_ids), 75):
            chunk = scryfall_ids[index : index + 75]
            save_cards(db, client.collection(chunk))
            result["scryfall_cards_cached"] = min(index + 75, len(scryfall_ids))
            status(scryfall_cards_cached=result["scryfall_cards_cached"])
            if index == 0 or (index + 75) % 375 == 0 or index + 75 >= len(scryfall_ids):
                log(f"Scryfall: {result['scryfall_cards_cached']}/{len(scryfall_ids)}")

        for uuid, entry in fetched_entries.items():
            save_mtgjson_price_entry(db, uuid, entry)
            entries[uuid] = entry

        all_points: list[dict[str, Any]] = []
        for uuid, deck_card in unique_by_uuid.items():
            entry = entries.get(uuid)
            if entry is None:
                continue
            all_points.extend(normalize_price_points(deck_card["scryfall_id"], entry))

        result["snapshots_written"] = save_external_price_snapshots(db, all_points)
        result["points"] = len(all_points)
        db.commit()
        status(points=len(all_points), snapshots_written=result["snapshots_written"])
        log(f"Historique prix ecrit: {result['snapshots_written']} snapshots.")

        if download_images:
            log(f"Telechargement des images: {len(scryfall_ids)} cartes...")
            rows = db.execute(
                "SELECT scryfall_id, raw_json FROM cards WHERE scryfall_id IN ({})".format(
                    ",".join("?" for _ in scryfall_ids)
                ),
                scryfall_ids,
            ).fetchall()
            cards_by_id = {row["scryfall_id"]: json.loads(row["raw_json"]) for row in rows}

            for index, scryfall_id in enumerate(scryfall_ids, start=1):
                card = cards_by_id.get(scryfall_id)
                if card is None:
                    result["images_failed"] += 1
                    continue
                image_url = large_image_url_for(card) or image_url_for(card)
                if not image_url:
                    result["images_failed"] += 1
                    continue
                downloaded = download_image(image_url, scryfall_id)
                if downloaded:
                    result["images_downloaded"] += 1
                else:
                    result["images_skipped"] += 1
                if index == 1 or index % 100 == 0 or index == len(scryfall_ids):
                    log(
                        f"Images: {index}/{len(scryfall_ids)} "
                        f"({result['images_downloaded']} telechargees, "
                        f"{result['images_skipped']} deja en cache)"
                    )

        db.close()
        result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status(running=False, finished_at=result["finished_at"])
        log("Prechargement termine.")
        return result
    except Exception as error:  # noqa: BLE001 - preload should capture failures for CLI/server.
        result["error"] = str(error)
        result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status(running=False, error=str(error), finished_at=result["finished_at"])
        raise
