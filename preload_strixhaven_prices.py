"""Preload MTGJSON price history for all sets from Strixhaven onwards."""
from __future__ import annotations

import sys
import time

from mtg_pwa.database import (
    connect,
    init_db,
    cached_mtgjson_price_entry,
    save_cards,
    save_external_price_snapshots,
    save_mtgjson_price_entry,
    save_mtgjson_uuid,
)
from mtg_pwa.local_cache import load_set_json
from mtg_pwa.mtgjson import extract_price_entries, normalize_price_points
from mtg_pwa.scryfall import ScryfallClient, ScryfallError
from mtg_pwa.sets_catalog import blocks_catalog

STX_RELEASE_DATE = "2021-04-23"


def sets_from_strixhaven() -> list[str]:
    codes: list[str] = []
    for block in blocks_catalog():
        for entry in block["sets"]:
            if (entry.get("release_date") or "") >= STX_RELEASE_DATE:
                codes.append(entry["code"])
    return codes


def collect_cards(set_codes: list[str]) -> dict[str, dict[str, str | None]]:
    cards: dict[str, dict[str, str | None]] = {}
    for code in set_codes:
        try:
            payload = load_set_json(code)
        except Exception as error:  # noqa: BLE001
            print(f"[skip] {code}: {error}", flush=True)
            continue
        for card in payload.get("cards") or []:
            if card.get("isFunny"):
                continue
            identifiers = card.get("identifiers") or {}
            scryfall_id = identifiers.get("scryfallId")
            uuid = card.get("uuid")
            if not scryfall_id or not uuid:
                continue
            cards[uuid] = {
                "scryfall_id": scryfall_id,
                "set_code": code,
                "collector_number": card.get("number"),
            }
    return cards


def main() -> None:
    started = time.time()
    set_codes = sets_from_strixhaven()
    cards_by_uuid = collect_cards(set_codes)
    print(f"Sets depuis Strixhaven: {len(set_codes)}", flush=True)
    print(f"Cartes uniques: {len(cards_by_uuid)}", flush=True)

    db = connect()
    init_db(db)

    for uuid, card in cards_by_uuid.items():
        save_mtgjson_uuid(
            db,
            scryfall_id=card["scryfall_id"],
            mtgjson_uuid=uuid,
            set_code=card["set_code"],
            collector_number=card["collector_number"],
        )
    db.commit()

    entries: dict[str, dict] = {}
    missing_uuids: list[str] = []
    for uuid in cards_by_uuid:
        cached = cached_mtgjson_price_entry(db, uuid)
        if cached is None:
            missing_uuids.append(uuid)
        else:
            entries[uuid] = cached

    print(f"Prix MTGJSON en cache: {len(entries)}, a telecharger: {len(missing_uuids)}", flush=True)

    if missing_uuids:
        print("Telechargement AllPrices MTGJSON (peut prendre longtemps)...", flush=True)
        fetched = extract_price_entries(missing_uuids)
        print(f"Prix recuperes: {len(fetched)}, manquants: {len(missing_uuids) - len(fetched)}", flush=True)
        for uuid, entry in fetched.items():
            save_mtgjson_price_entry(db, uuid, entry)
            entries[uuid] = entry
        db.commit()

    scryfall_ids = sorted({card["scryfall_id"] for card in cards_by_uuid.values()})
    existing: set[str] = set()
    for index in range(0, len(scryfall_ids), 500):
        chunk = scryfall_ids[index : index + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = db.execute(
            f"SELECT scryfall_id FROM cards WHERE scryfall_id IN ({placeholders})",
            chunk,
        ).fetchall()
        existing.update(row[0] for row in rows)
    missing_scryfall = [sid for sid in scryfall_ids if sid not in existing]
    if missing_scryfall:
        client = ScryfallClient()
        print(f"Cache Scryfall: {len(missing_scryfall)} cartes manquantes...", flush=True)
        for index in range(0, len(missing_scryfall), 75):
            chunk = missing_scryfall[index : index + 75]
            try:
                save_cards(db, client.collection(chunk))
                db.commit()
            except ScryfallError as error:
                print(f"Scryfall lot {index // 75 + 1}: {error}", file=sys.stderr, flush=True)
            done = min(index + 75, len(missing_scryfall))
            if index == 0 or done % 750 == 0 or done == len(missing_scryfall):
                print(f"  Scryfall {done}/{len(missing_scryfall)}", flush=True)
    else:
        print(f"Cache Scryfall deja a jour ({len(scryfall_ids)} cartes).", flush=True)

    print("Ecriture des snapshots...", flush=True)
    written = 0
    cards_with_prices = 0
    for uuid, card in cards_by_uuid.items():
        entry = entries.get(uuid)
        if entry is None:
            continue
        points = normalize_price_points(card["scryfall_id"], entry)
        if not points:
            continue
        written += save_external_price_snapshots(db, points)
        cards_with_prices += 1
        if cards_with_prices % 500 == 0:
            db.commit()
            print(f"  {cards_with_prices} cartes, {written} snapshots", flush=True)
    db.commit()

    elapsed = int(time.time() - started)
    print(
        f"Termine en {elapsed}s: {len(entries)} cartes avec prix, "
        f"{written} snapshots ecrits/mis a jour.",
        flush=True,
    )


if __name__ == "__main__":
    main()
