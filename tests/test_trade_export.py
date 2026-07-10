from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_pwa.cardmarket_export import build_cardmarket_order_plan, estimate_shipping_eur
from mtg_pwa.collection_extras import (
    export_trade_hw_text,
    match_trade_import,
    parse_trade_decklist_text,
    trade_lines_total_eur,
)
from mtg_pwa.database import connect, init_db, save_cardmarket_price_guide_daily, save_cardmarket_product_mappings


class TradeExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.conn = connect(self.db_path)
        init_db(self.conn)
        save_cardmarket_product_mappings(
            self.conn,
            [{"id_product": 1, "scryfall_id": "abc", "set_code": "M10", "collector_number": "1"}],
        )
        save_cardmarket_price_guide_daily(
            self.conn,
            [
                {
                    "id_product": 1,
                    "snapshot_date": "2026-07-09",
                    "trend": 2.0,
                    "low_price": 1.0,
                    "avg7": 1.8,
                    "collected_at": "t",
                }
            ],
        )
        self.conn.execute(
            """
            INSERT INTO cards (scryfall_id, name, set_code, set_name, raw_json, updated_at)
            VALUES ('abc', 'Lightning Bolt', 'M10', 'Magic 2010', '{"name":"Lightning Bolt","set":"M10"}', '2026-07-09')
            """
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_estimate_shipping_eur(self) -> None:
        result = estimate_shipping_eur(10, "letter")
        self.assertEqual(result["estimated_eur"], 4.0)
        self.assertEqual(result["card_count"], 10)

    def test_order_plan_includes_low_and_shipping(self) -> None:
        plan = build_cardmarket_order_plan(
            self.conn,
            [{"scryfall_id": "abc", "name": "Lightning Bolt", "set_name": "M10", "quantity": 2, "finish": "nonfoil"}],
            shipping_profile="letter",
        )
        self.assertEqual(plan["estimated_subtotal_low"], 2.0)
        self.assertEqual(plan["estimated_subtotal_trend"], 4.0)
        self.assertEqual(plan["products"][0]["low"], 1.0)
        self.assertIn("csv", plan["exports"])
        self.assertGreater(plan["estimated_total_trend"], plan["estimated_subtotal_trend"])

    def test_parse_trade_decklist_hw(self) -> None:
        text = "H:\n1 Bolt (M10)\n\nW:\n2 Counterspell (M10)"
        have, want = parse_trade_decklist_text(text)
        self.assertEqual(len(have), 1)
        self.assertEqual(have[0]["name"], "Bolt")
        self.assertEqual(len(want), 1)
        self.assertEqual(want[0]["quantity"], 2)

    def test_export_trade_hw_text(self) -> None:
        text = export_trade_hw_text(
            [{"name": "Bolt", "set_code": "M10", "quantity": 1}],
            [{"name": "Counterspell", "set_code": "M10", "quantity": 2}],
        )
        self.assertIn("H:", text)
        self.assertIn("W:", text)
        self.assertIn("Counterspell", text)

    def test_trade_lines_total(self) -> None:
        total = trade_lines_total_eur([{"quantity": 2, "unit_price_eur": 1.5}])
        self.assertEqual(total, 3.0)

    def test_match_trade_import(self) -> None:
        result = match_trade_import(self.conn, "1 Lightning Bolt (M10)")
        self.assertEqual(len(result["matched"]), 1)
        self.assertEqual(result["matched"][0]["scryfall_id"], "abc")


if __name__ == "__main__":
    unittest.main()
