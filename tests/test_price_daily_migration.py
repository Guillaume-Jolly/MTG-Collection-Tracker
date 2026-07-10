from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_pwa.database import connect, init_db
from mtg_pwa.price_daily import (
    install_price_snapshots_view,
    migrate_snapshots_to_daily,
    upsert_price_daily_points,
    verify_migration,
)


class PriceDailyMigrationTest(unittest.TestCase):
    def _prepare_legacy_table(self, conn) -> None:
        conn.execute("DROP TABLE IF EXISTS price_snapshots")
        conn.execute("DROP VIEW IF EXISTS price_snapshots")
        conn.execute("DROP TABLE IF EXISTS price_snapshots_legacy")
        conn.execute(
            """
            CREATE TABLE price_snapshots_legacy (
                id INTEGER PRIMARY KEY,
                scryfall_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                finish TEXT NOT NULL,
                price REAL NOT NULL,
                source TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                collected_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def test_verify_migration_matches_active_eur_sources_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            conn = connect(db_path)
            init_db(conn)
            self._prepare_legacy_table(conn)
            rows = [
                ("card-a", "EUR", "nonfoil", 1.0, "scryfall-cardmarket", "2026-07-01"),
                ("card-a", "USD", "nonfoil", 2.0, "mtgjson-tcgplayer", "2026-07-01"),
                ("card-b", "EUR", "foil", 3.0, "scryfall-cardmarket", "2026-07-01"),
            ]
            for scryfall_id, currency, finish, price, source, snapshot_date in rows:
                conn.execute(
                    """
                    INSERT INTO price_snapshots_legacy (
                        scryfall_id, currency, finish, price, source, snapshot_date, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '2026-07-01T00:00:00Z')
                    """,
                    (scryfall_id, currency, finish, price, source, snapshot_date),
                )
            conn.commit()

            migrate_snapshots_to_daily(conn)
            install_price_snapshots_view(conn)
            check = verify_migration(conn)
            conn.close()

            self.assertEqual(check["legacy_narrow_rows"], 3)
            self.assertEqual(check["legacy_active_rows"], 2)
            self.assertEqual(check["daily_price_cells"], 2)
            self.assertEqual(check["view_narrow_rows"], 2)
            self.assertTrue(check["match"])

    def test_upsert_increments_active_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            conn = connect(db_path)
            init_db(conn)
            self._prepare_legacy_table(conn)
            install_price_snapshots_view(conn)
            upsert_price_daily_points(
                conn,
                [
                    {
                        "scryfall_id": "card-z",
                        "finish": "nonfoil",
                        "source": "scryfall-cardmarket",
                        "price": 4.5,
                        "snapshot_date": "2026-07-10",
                    }
                ],
            )
            check = verify_migration(conn)
            conn.close()

            self.assertEqual(check["legacy_active_rows"], 0)
            self.assertEqual(check["daily_price_cells"], 1)
            self.assertEqual(check["view_narrow_rows"], 1)
            self.assertTrue(check["match"])


if __name__ == "__main__":
    unittest.main()
