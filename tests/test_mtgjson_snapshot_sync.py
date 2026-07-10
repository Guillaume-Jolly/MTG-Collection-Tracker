from __future__ import annotations

import tempfile
import unittest

from mtg_pwa.database import connect, init_db, save_card
from mtg_pwa.mtgjson import normalize_price_points
from mtg_pwa.server import mtgjson_snapshots_need_sync, sync_mtgjson_price_snapshots


class MtgjsonSnapshotSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.conn = connect(f"{self.tempdir.name}/test.sqlite3")
        init_db(self.conn)
        save_card(self.conn, {"id": "card-1", "name": "Test Card", "prices": {"eur": "1.00"}})
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_skips_usd_mtgjson_sources_in_eur_only_mode(self) -> None:
        price_entry = {
            "paper": {
                "cardkingdom": {
                    "currency": "USD",
                    "retail": {
                        "normal": {
                            "2026-06-20": 8.1,
                            "2026-06-29": 8.5,
                        }
                    },
                }
            }
        }
        points = normalize_price_points("card-1", price_entry)
        self.assertFalse(mtgjson_snapshots_need_sync(self.conn, "card-1", points))
        self.assertEqual(sync_mtgjson_price_snapshots(self.conn, "card-1", price_entry), 0)
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS quantity
            FROM price_daily
            WHERE scryfall_id = ? AND ck_nonfoil IS NOT NULL
            """,
            ("card-1",),
        ).fetchone()
        self.assertEqual(int(row["quantity"]), 0)


if __name__ == "__main__":
    unittest.main()
