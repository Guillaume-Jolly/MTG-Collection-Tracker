from __future__ import annotations

import tempfile
import unittest

from mtg_pwa.database import connect, init_db, save_card, save_external_price_snapshots
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

    def test_syncs_when_no_mtgjson_snapshots_exist(self) -> None:
        price_entry = {
            "paper": {
                "cardmarket": {
                    "currency": "EUR",
                    "retail": {
                        "normal": {
                            "2026-06-20": 8.1,
                            "2026-06-29": 8.5,
                        }
                    },
                }
            }
        }
        self.assertTrue(
            mtgjson_snapshots_need_sync(
                self.conn,
                "card-1",
                [
                    {
                        "scryfall_id": "card-1",
                        "currency": "EUR",
                        "finish": "nonfoil",
                        "price": 8.5,
                        "source": "mtgjson-cardmarket",
                        "snapshot_date": "2026-06-29",
                        "collected_at": "2026-06-29T00:00:00Z",
                    }
                ],
            )
        )
        written = sync_mtgjson_price_snapshots(self.conn, "card-1", price_entry)
        self.assertEqual(written, 2)
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS quantity, MIN(snapshot_date) AS first_date, MAX(snapshot_date) AS last_date
            FROM price_snapshots
            WHERE scryfall_id = ? AND source = 'mtgjson-cardmarket'
            """,
            ("card-1",),
        ).fetchone()
        self.assertEqual(int(row["quantity"]), 2)
        self.assertEqual(row["first_date"], "2026-06-20")
        self.assertEqual(row["last_date"], "2026-06-29")

    def test_skips_sync_when_history_is_complete(self) -> None:
        points = [
            {
                "scryfall_id": "card-1",
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 8.1,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-20",
                "collected_at": "2026-06-20T00:00:00Z",
            },
            {
                "scryfall_id": "card-1",
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 8.5,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-29",
                "collected_at": "2026-06-29T00:00:00Z",
            },
        ]
        save_external_price_snapshots(self.conn, points)
        price_entry = {
            "paper": {
                "cardmarket": {
                    "currency": "EUR",
                    "retail": {"normal": {"2026-06-20": 8.1, "2026-06-29": 8.5}},
                }
            }
        }
        self.assertFalse(mtgjson_snapshots_need_sync(self.conn, "card-1", points))
        self.assertEqual(sync_mtgjson_price_snapshots(self.conn, "card-1", price_entry), 0)


if __name__ == "__main__":
    unittest.main()
