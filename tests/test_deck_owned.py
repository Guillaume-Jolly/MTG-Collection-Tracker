from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from mtg_pwa.database import (
    backfill_owned_decks_from_imports,
    connect,
    get_app_metadata,
    init_db,
    is_deck_owned,
    set_deck_owned,
    utc_now,
)


class DeckOwnedBackfillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.conn = connect(f"{self.tempdir.name}/test.sqlite3")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_manual_unown_is_not_reverted_by_backfill(self) -> None:
        file_name = "turtle-power.json"
        deck_name = "Turtle Power!"

        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO cards (
                scryfall_id, oracle_id, name, printed_name, lang, set_code, set_name,
                collector_number, rarity, image_url, scryfall_uri, raw_json, updated_at
            )
            VALUES (?, NULL, 'Test Card', NULL, 'en', 'TST', 'Test', '1', 'common', NULL, NULL, '{}', ?)
            """,
            ("card-1", now),
        )
        self.conn.execute(
            """
            INSERT INTO collection_items (
                scryfall_id, quantity, finish, condition, language,
                purchase_price, purchase_currency, purchase_date, notes, created_at, updated_at
            )
            VALUES ('card-1', 1, 'nonfoil', 'NM', 'en', NULL, 'EUR', NULL, ?, ?, ?)
            """,
            (f"Import precon: {deck_name}", now, now),
        )
        self.conn.commit()
        set_deck_owned(self.conn, file_name, True)
        set_deck_owned(self.conn, file_name, False)
        self.assertFalse(is_deck_owned(self.conn, file_name))

        self.conn.execute("DELETE FROM app_metadata WHERE key = ?", ("owned_decks_import_backfill_v1",))

        with patch(
            "mtg_pwa.local_cache.load_deck_list",
            return_value=[{"fileName": file_name, "name": deck_name}],
        ):
            added = backfill_owned_decks_from_imports(self.conn)

        self.assertEqual(added, 0)
        self.assertFalse(is_deck_owned(self.conn, file_name))

    def test_backfill_runs_only_once(self) -> None:
        self.assertEqual(get_app_metadata(self.conn, "owned_decks_import_backfill_v1"), "1")

        with patch("mtg_pwa.local_cache.load_deck_list") as load_deck_list:
            added = backfill_owned_decks_from_imports(self.conn)

        self.assertEqual(added, 0)
        load_deck_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
