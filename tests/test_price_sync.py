from __future__ import annotations

import json
import sqlite3
import unittest

from mtg_pwa.database import init_db, save_card, save_external_price_snapshots, save_mtgjson_price_entry, save_mtgjson_uuid, save_price_snapshots
from mtg_pwa.price_sync import (
    card_price_sync_plan,
    mtgjson_prices_fresh,
    needs_price_fallback,
    scryfall_prices_fresh,
)


def _sample_card(**overrides) -> dict:
    card = {
        "id": "abc-123",
        "set": "mh2",
        "collector_number": "1",
        "lang": "fr",
        "updated_at": "2024-01-15T10:00:00.000Z",
        "prices": {"eur": "1.50", "eur_foil": None},
        "finishes": ["nonfoil"],
    }
    card.update(overrides)
    return card


class PriceSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_scryfall_prices_fresh_when_snapshot_matches_updated_at(self) -> None:
        card = _sample_card()
        save_card(self.conn, card)
        save_price_snapshots(self.conn, card)
        self.assertTrue(scryfall_prices_fresh(self.conn, card))

    def test_scryfall_prices_stale_when_updated_at_differs(self) -> None:
        card = _sample_card()
        save_card(self.conn, card)
        save_price_snapshots(self.conn, card)
        card["updated_at"] = "2024-02-01T12:00:00.000Z"
        self.assertFalse(scryfall_prices_fresh(self.conn, card))

    def test_card_price_sync_plan_skips_when_fresh(self) -> None:
        card = _sample_card(lang="en")
        save_card(self.conn, card)
        save_price_snapshots(self.conn, card)
        save_mtgjson_uuid(
            self.conn,
            scryfall_id=card["id"],
            mtgjson_uuid="uuid-1",
            set_code=card["set"],
            collector_number=card["collector_number"],
        )
        price_entry = {
            "paper": {
                "cardmarket": {
                    "currency": "EUR",
                    "retail": {"normal": {"2024-01-01": 1.5}},
                }
            }
        }
        save_mtgjson_price_entry(self.conn, "uuid-1", price_entry)
        from mtg_pwa.mtgjson import normalize_price_points

        save_external_price_snapshots(self.conn, normalize_price_points(card["id"], price_entry))
        plan = card_price_sync_plan(self.conn, card["id"])
        self.assertTrue(plan["skip"])

    def test_card_price_sync_plan_needs_scryfall_when_missing_card(self) -> None:
        plan = card_price_sync_plan(self.conn, "missing-id")
        self.assertTrue(plan["needs_scryfall"])
        self.assertFalse(plan["skip"])

    def test_needs_price_fallback_for_french_without_snapshot(self) -> None:
        card = _sample_card(prices={"eur": None}, lang="fr")
        save_card(self.conn, card)
        self.assertTrue(needs_price_fallback(self.conn, card))

    def test_mtgjson_prices_not_fresh_without_cache(self) -> None:
        card = _sample_card()
        save_card(self.conn, card)
        self.assertFalse(mtgjson_prices_fresh(self.conn, card))


if __name__ == "__main__":
    unittest.main()
