from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_pwa.database import adjust_collection_quantity, connect, init_db, save_card
from mtg_pwa.server import collection_valuation_history


class CollectionHistoryTest(unittest.TestCase):
    def test_collection_history_uses_live_prices_for_entire_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)

            priced_card = {
                "id": "00000000-0000-0000-0000-000000000011",
                "name": "Priced Card",
                "prices": {"eur": "2.00"},
            }
            live_only_card = {
                "id": "00000000-0000-0000-0000-000000000012",
                "name": "Live Card",
                "prices": {"eur": "3.50"},
            }
            save_card(conn, priced_card)
            save_card(conn, live_only_card)
            adjust_collection_quantity(conn, scryfall_id=priced_card["id"], finish="nonfoil", delta=2)
            adjust_collection_quantity(conn, scryfall_id=live_only_card["id"], finish="nonfoil", delta=1)
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, currency, finish, price, source, snapshot_date,
                    collected_at, source_updated_at
                )
                VALUES (?, 'EUR', 'nonfoil', ?, 'mtgjson-cardmarket', ?, ?, NULL)
                """,
                (
                    priced_card["id"],
                    1.0,
                    "2026-06-21",
                    "2026-06-21T00:00:00+00:00",
                ),
            )
            conn.commit()

            payload = collection_valuation_history(conn, "cardmarket")
            conn.close()

            self.assertAlmostEqual(payload["current_total_eur"], 7.5)
            self.assertEqual(payload["priced_cards"], 3)
            self.assertEqual(payload["missing_cards"], 0)
            self.assertTrue(payload["history"])
            latest = payload["history"][-1]
            self.assertAlmostEqual(latest["total_eur"], 7.5)
            self.assertEqual(latest["priced_cards"], 3)

            june_point = next(
                point for point in payload["history"] if point["snapshot_date"] == "2026-06-21"
            )
            self.assertAlmostEqual(june_point["total_eur"], 5.5)
            self.assertEqual(june_point["priced_cards"], 3)


if __name__ == "__main__":
    unittest.main()
