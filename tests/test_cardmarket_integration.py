from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_pwa.cardmarket_export import build_cardmarket_order_plan, build_wants_decklist_line
from mtg_pwa.cardmarket_retention import compact_cardmarket_guide_history
from mtg_pwa.database import (
    CARDMARKET_GUIDE_SOURCE,
    connect,
    init_db,
    merge_cardmarket_history_points,
    price_history,
    save_cardmarket_price_guide_daily,
    save_cardmarket_product_mappings,
    save_mtgjson_uuid,
)
from mtg_pwa.server import (
    cardmarket_metrics_liquid,
    matches_speculative_preset,
    market_mover_rows_from_guide,
)


class CardmarketIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp_dir.name) / "test.sqlite3")
        init_db(self.conn)
        save_mtgjson_uuid(
            self.conn,
            scryfall_id="abc",
            mtgjson_uuid="uuid-1",
            set_code="STX",
            collector_number="1",
        )
        save_cardmarket_product_mappings(
            self.conn,
            [{"id_product": 556813, "scryfall_id": "abc", "set_code": "STX", "collector_number": "1"}],
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_card_row(self) -> None:
        self.conn.execute(
            """
            INSERT INTO cards (
                scryfall_id, oracle_id, name, set_code, set_name, collector_number,
                rarity, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("abc", "oracle", "Test", "STX", "Strixhaven", "1", "rare", "{}", "t"),
        )

    def test_merge_guide_over_legacy_snapshot(self) -> None:
        save_cardmarket_price_guide_daily(
            self.conn,
            [
                {
                    "id_product": 556813,
                    "snapshot_date": "2026-06-30",
                    "trend": 0.07,
                    "low_price": 0.02,
                    "avg": 0.11,
                    "avg1": 0.02,
                    "avg7": 0.11,
                    "avg30": 0.1,
                    "collected_at": "2026-06-30T10:00:00+00:00",
                }
            ],
        )
        self._insert_card_row()
        self.conn.execute(
            """
            INSERT INTO price_snapshots (
                scryfall_id, finish, snapshot_date, price, source, currency, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("abc", "nonfoil", "2026-06-30", 0.05, "mtgjson-cardmarket", "EUR", "t"),
        )
        self.conn.execute(
            """
            INSERT INTO price_snapshots (
                scryfall_id, finish, snapshot_date, price, source, currency, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("abc", "nonfoil", "2026-03-01", 0.04, "mtgjson-cardmarket", "EUR", "t"),
        )
        self.conn.commit()
        history = price_history(self.conn, "abc", "nonfoil")
        by_date = {point["snapshot_date"]: point for point in history}
        self.assertEqual(by_date["2026-06-30"]["source"], CARDMARKET_GUIDE_SOURCE)
        self.assertEqual(by_date["2026-06-30"]["data_tier"], "guide")
        self.assertEqual(by_date["2026-03-01"]["data_tier"], "legacy")

    def test_market_mover_rows_from_guide(self) -> None:
        for day, trend in (("2026-06-01", 1.0), ("2026-06-30", 2.0)):
            save_cardmarket_price_guide_daily(
                self.conn,
                [
                    {
                        "id_product": 556813,
                        "snapshot_date": day,
                        "trend": trend,
                        "low_price": trend,
                        "avg": trend,
                        "avg1": trend,
                        "avg7": trend,
                        "avg30": trend,
                        "collected_at": "t",
                    }
                ],
            )
        self.conn.execute(
            """
            INSERT INTO cards (
                scryfall_id, oracle_id, name, set_code, set_name, collector_number,
                rarity, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("abc", "oracle", "Test", "STX", "Strixhaven", "1", "rare", "{}", "t"),
        )
        self.conn.commit()
        rows = market_mover_rows_from_guide(
            self.conn,
            "2026-06-01",
            "2026-06-30",
            eligible_set_codes=frozenset({"STX"}),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["start_price"]), 1.0)
        self.assertEqual(float(rows[0]["end_price"]), 2.0)

    def test_order_plan_without_product_map(self) -> None:
        plan = build_cardmarket_order_plan(
            self.conn,
            [{"scryfall_id": "missing", "name": "X", "set_name": "Y", "quantity": 1}],
        )
        self.assertEqual(plan["products_mapped"], 0)
        self.assertIn("missing", plan["missing_product_map"])

    def test_retention_compacts_old_rows(self) -> None:
        for day in ("2025-01-01", "2025-01-15", "2025-02-01"):
            save_cardmarket_price_guide_daily(
                self.conn,
                [
                    {
                        "id_product": 556813,
                        "snapshot_date": day,
                        "trend": 1.0,
                        "collected_at": "t",
                    }
                ],
            )
        self.conn.commit()
        result = compact_cardmarket_guide_history(self.conn, as_of=__import__("datetime").date(2026, 6, 30))
        self.assertGreaterEqual(result["deleted_yearly_thinned"], 1)

    def test_liquidity_and_preset_helpers(self) -> None:
        self.assertFalse(
            cardmarket_metrics_liquid({"trend": 1.0, "low": 0.1, "avg1": 1.0}),
        )
        self.assertTrue(matches_speculative_preset(["ancienne", "prix_stable", "spike_sur_stabilite"], "stable_spike"))
        self.assertEqual(build_wants_decklist_line(quantity=4, name="Bolt", set_name="M10"), "4x Bolt (M10)")


if __name__ == "__main__":
    unittest.main()
