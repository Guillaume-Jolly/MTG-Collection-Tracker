from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from mtg_pwa.cardmarket_export import (
    build_product_mappings_for_set,
    load_price_guide,
    price_guide_entry_to_row,
    refresh_cardmarket_product_map,
)
from mtg_pwa.database import (
    cardmarket_product_id_by_scryfall,
    connect,
    init_db,
    save_cardmarket_price_guide_daily,
    save_cardmarket_product_mappings,
    save_mtgjson_uuid,
    set_app_metadata,
)


class CardmarketExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.conn = connect(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_price_guide_entry_to_row_maps_foil_fields(self) -> None:
        row = price_guide_entry_to_row(
            {
                "idProduct": 556813,
                "idCategory": 1,
                "avg": 0.11,
                "low": 0.02,
                "trend": 0.07,
                "avg1": 0.02,
                "avg7": 0.11,
                "avg30": 0.1,
                "avg-foil": 0.3,
                "low-foil": 0.02,
                "trend-foil": 0.2,
                "avg1-foil": 0.04,
                "avg7-foil": 0.17,
                "avg30-foil": 0.24,
            },
            snapshot_date="2026-06-30",
            guide_version=2,
            guide_created_at="2026-06-30T08:00:00+02:00",
            collected_at="2026-06-30T10:00:00+00:00",
        )
        self.assertEqual(row["id_product"], 556813)
        self.assertEqual(row["low_price"], 0.02)
        self.assertEqual(row["avg7_foil"], 0.17)
        self.assertEqual(row["guide_version"], 2)

    def test_build_product_mappings_for_set_reads_mcm_id(self) -> None:
        set_payload = {
            "code": "STX",
            "cards": [
                {
                    "number": "1",
                    "identifiers": {"scryfallId": "abc", "mcmId": 556813},
                },
                {
                    "number": "2",
                    "identifiers": {"scryfallId": "def"},
                },
            ],
        }
        with patch("mtg_pwa.cardmarket_export.load_set_json", return_value=set_payload):
            mappings = build_product_mappings_for_set("STX")
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["id_product"], 556813)
        self.assertEqual(mappings[0]["scryfall_id"], "abc")
        self.assertEqual(mappings[0]["set_code"], "STX")

    def test_save_cardmarket_tables_round_trip(self) -> None:
        save_mtgjson_uuid(
            self.conn,
            scryfall_id="abc",
            mtgjson_uuid="uuid-1",
            set_code="STX",
            collector_number="1",
        )
        self.conn.commit()
        save_cardmarket_product_mappings(
            self.conn,
            [{"id_product": 556813, "scryfall_id": "abc", "set_code": "STX", "collector_number": "1"}],
        )
        self.conn.commit()
        mapped = cardmarket_product_id_by_scryfall(self.conn, ["abc"])
        self.assertEqual(mapped["abc"], 556813)

        written = save_cardmarket_price_guide_daily(
            self.conn,
            [
                price_guide_entry_to_row(
                    {
                        "idProduct": 556813,
                        "trend": 0.07,
                        "low": 0.02,
                        "avg": 0.11,
                        "avg1": 0.02,
                        "avg7": 0.11,
                        "avg30": 0.1,
                    },
                    snapshot_date="2026-06-30",
                    guide_version=1,
                    guide_created_at="2026-06-30",
                    collected_at="2026-06-30T10:00:00+00:00",
                )
            ],
        )
        self.conn.commit()
        self.assertEqual(written, 1)
        row = self.conn.execute(
            "SELECT trend, avg7, low_price FROM cardmarket_price_guide_daily WHERE id_product = ?",
            (556813,),
        ).fetchone()
        self.assertEqual(row["trend"], 0.07)
        self.assertEqual(row["avg7"], 0.11)
        self.assertEqual(row["low_price"], 0.02)

    def test_refresh_cardmarket_product_map_uses_tracked_sets(self) -> None:
        save_mtgjson_uuid(
            self.conn,
            scryfall_id="abc",
            mtgjson_uuid="uuid-1",
            set_code="STX",
            collector_number="1",
        )
        self.conn.commit()
        set_payload = {
            "code": "STX",
            "cards": [{"number": "1", "identifiers": {"scryfallId": "abc", "mcmId": 556813}}],
        }
        with patch("mtg_pwa.cardmarket_export.cached_set_codes", return_value=["STX"]), patch(
            "mtg_pwa.cardmarket_export.load_set_json", return_value=set_payload
        ):
            count = refresh_cardmarket_product_map(self.conn)
        self.conn.commit()
        self.assertEqual(count, 1)
        self.assertEqual(cardmarket_product_id_by_scryfall(self.conn, ["abc"])["abc"], 556813)

    def test_load_price_guide_from_cache_file(self) -> None:
        guide_path = Path(self.temp_dir.name) / "guide.json"
        payload = {
            "version": 1,
            "createdAt": "2026-06-30",
            "priceGuides": [{"idProduct": 1, "trend": 1.0, "low": 0.5, "avg": 0.8, "avg1": 0.7, "avg7": 0.6, "avg30": 0.5}],
        }
        guide_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_price_guide(guide_path)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["priceGuides"]), 1)

    def test_cardmarket_archive_skips_when_already_done(self) -> None:
        from mtg_pwa.cardmarket_export import archive_daily_cardmarket_prices

        save_mtgjson_uuid(
            self.conn,
            scryfall_id="abc",
            mtgjson_uuid="uuid-1",
            set_code="STX",
            collector_number="1",
        )
        self.conn.commit()
        set_app_metadata(self.conn, "last_cardmarket_archive_date", date.today().isoformat())
        self.conn.commit()
        self.conn.close()

        with patch("mtg_pwa.cardmarket_export.download_price_guide") as download_mock:
            result = archive_daily_cardmarket_prices(db_path=str(self.db_path), force=False)
        self.assertTrue(result["skipped"])
        download_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
