from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mtg_pwa.database import (
    catalog_table,
    connect,
    init_db,
    save_card,
    save_external_price_snapshots,
    shared_prices_db_path,
    uses_shared_catalog,
)


class SharedCatalogTest(unittest.TestCase):
    def test_prod_db_reads_prices_from_shared_dev_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dev_db = Path(tmp) / "dev.sqlite3"
            prod_db = Path(tmp) / "prod.sqlite3"

            dev_conn = connect(dev_db)
            init_db(dev_conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000061",
                "name": "Shared Card",
                "rarity": "rare",
                "prices": {"eur": "3.00"},
            }
            save_card(dev_conn, card)
            save_external_price_snapshots(
                dev_conn,
                [
                    {
                        "scryfall_id": card["id"],
                        "currency": "EUR",
                        "finish": "nonfoil",
                        "price": 3.0,
                        "source": "mtgjson-cardmarket",
                        "snapshot_date": "2026-06-30",
                        "collected_at": "2026-06-30T00:00:00+00:00",
                    }
                ],
            )
            dev_conn.commit()
            dev_conn.close()

            os.environ["MTG_PWA_PRICES_DB"] = str(dev_db)
            try:
                self.assertEqual(shared_prices_db_path(), dev_db.resolve())
                self.assertTrue(uses_shared_catalog())

                prod_conn = connect(prod_db)
                init_db(prod_conn)
                snapshots_table = catalog_table("price_snapshots")
                row = prod_conn.execute(
                    f"""
                    SELECT price
                    FROM {snapshots_table}
                    WHERE scryfall_id = ? AND snapshot_date = '2026-06-30'
                    """,
                    (card["id"],),
                ).fetchone()
                prod_conn.close()
                dev_conn.close()
            finally:
                os.environ.pop("MTG_PWA_PRICES_DB", None)

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(float(row["price"]), 3.0)


if __name__ == "__main__":
    unittest.main()
