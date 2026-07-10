from __future__ import annotations

import tempfile
import unittest

from mtg_pwa.database import add_collection_item, catalog_table, connect, init_db, utc_now
from mtg_pwa.server import HistoryBuildOptions, deck_valuation_history_fast
import json


class DeckHistoryFastTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.conn = connect(f"{self.tempdir.name}/test.sqlite3")
        init_db(self.conn)
        cards_table = catalog_table("cards")
        raw = {
            "id": "card-1",
            "name": "Bolt",
            "set": "tst",
            "collector_number": "1",
            "lang": "en",
            "rarity": "common",
        }
        self.conn.execute(
            f"""
            INSERT INTO {cards_table} (
                scryfall_id, oracle_id, name, printed_name, lang, set_code, set_name,
                collector_number, rarity, image_url, scryfall_uri, raw_json, updated_at
            )
            VALUES ('card-1', NULL, 'Bolt', NULL, 'en', 'tst', 'TST', '1', 'common', NULL, NULL, ?, ?)
            """,
            (json.dumps(raw), utc_now()),
        )
        add_collection_item(
            self.conn,
            scryfall_id="card-1",
            quantity=2,
            finish="nonfoil",
            condition="near_mint",
            language="en",
            purchase_price=None,
            purchase_currency="EUR",
            purchase_date=None,
            notes=None,
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_deck_history_fast_returns_single_point(self) -> None:
        deck_cards = [
            {
                "scryfall_id": "card-1",
                "finish": "nonfoil",
                "quantity": 2,
            }
        ]
        payload = deck_valuation_history_fast(
            self.conn,
            deck_cards,
            "cardmarket",
            HistoryBuildOptions(),
            archive_meta={"archive_days": 1},
        )
        self.assertEqual(payload["history_mode"], "fast")
        self.assertEqual(len(payload["history"]), 1)
        self.assertIn("total_eur", payload["history"][0])
