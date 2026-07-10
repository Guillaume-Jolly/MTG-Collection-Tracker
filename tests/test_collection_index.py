from __future__ import annotations

import json
import tempfile
import unittest

from mtg_pwa.collection_index import (
    DISPLAY_LANGS,
    ensure_collection_app_tables,
    invalidate_collection_owned_index,
    list_owned_from_index,
    mark_collection_index_dirty,
    rebuild_collection_owned_index,
    sync_collection_owned_index,
)
from mtg_pwa.database import add_collection_item, catalog_table, connect, init_db, utc_now


class CollectionIndexIncrementalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.conn = connect(f"{self.tempdir.name}/test.sqlite3")
        init_db(self.conn)
        ensure_collection_app_tables(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def _seed_card(self, scryfall_id: str, *, name: str, set_code: str = "tst") -> None:
        cards_table = catalog_table("cards")
        raw = {
            "id": scryfall_id,
            "name": name,
            "set": set_code,
            "collector_number": "1",
            "lang": "en",
            "rarity": "common",
            "type_line": "Creature",
            "cmc": 1,
            "color_identity": [],
        }
        self.conn.execute(
            f"""
            INSERT INTO {cards_table} (
                scryfall_id, oracle_id, name, printed_name, lang, set_code, set_name,
                collector_number, rarity, image_url, scryfall_uri, raw_json, updated_at
            )
            VALUES (?, NULL, ?, NULL, 'en', ?, ?, '1', 'common', NULL, NULL, ?, ?)
            """,
            (scryfall_id, name, set_code, set_code.upper(), json.dumps(raw), utc_now()),
        )

    def test_incremental_index_updates_single_card(self) -> None:
        self._seed_card("card-a", name="Alpha")
        self._seed_card("card-b", name="Beta")
        add_collection_item(
            self.conn,
            scryfall_id="card-a",
            quantity=1,
            finish="nonfoil",
            condition="near_mint",
            language="en",
            purchase_price=None,
            purchase_currency="EUR",
            purchase_date=None,
            notes=None,
        )
        add_collection_item(
            self.conn,
            scryfall_id="card-b",
            quantity=1,
            finish="nonfoil",
            condition="near_mint",
            language="en",
            purchase_price=None,
            purchase_currency="EUR",
            purchase_date=None,
            notes=None,
        )
        self.conn.commit()

        rebuild_collection_owned_index(self.conn, display_lang="fr")
        self.conn.commit()

        before = list_owned_from_index(self.conn, sort="name_asc", display_lang="fr", limit=50, offset=0)
        self.assertEqual(before["pagination"]["total"], 2)

        self.conn.execute(
            "UPDATE collection_items SET quantity = 0 WHERE scryfall_id = 'card-b' AND finish = 'nonfoil'"
        )
        self.conn.commit()
        mark_collection_index_dirty(self.conn, {"card-b"})
        sync_collection_owned_index(self.conn, "fr")
        self.conn.commit()

        after = list_owned_from_index(self.conn, sort="name_asc", display_lang="fr", limit=50, offset=0)
        self.assertEqual(after["pagination"]["total"], 1)
        self.assertEqual(after["cards"][0]["scryfall_id"], "card-a")

    def test_mark_dirty_covers_all_display_langs(self) -> None:
        mark_collection_index_dirty(self.conn, {"card-x"})
        rows = self.conn.execute(
            "SELECT display_lang FROM collection_index_dirty ORDER BY display_lang"
        ).fetchall()
        self.assertEqual(sorted(row["display_lang"] for row in rows), sorted(DISPLAY_LANGS))

    def test_invalidate_with_scryfall_ids_keeps_index_rows(self) -> None:
        self._seed_card("card-a", name="Alpha")
        add_collection_item(
            self.conn,
            scryfall_id="card-a",
            quantity=1,
            finish="nonfoil",
            condition="near_mint",
            language="en",
            purchase_price=None,
            purchase_currency="EUR",
            purchase_date=None,
            notes=None,
        )
        self.conn.commit()

        rebuild_collection_owned_index(self.conn, display_lang="fr")
        self.conn.commit()

        count_before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM collection_owned_index WHERE display_lang = 'fr'"
        ).fetchone()["c"]
        self.assertEqual(count_before, 1)

        invalidate_collection_owned_index(self.conn, scryfall_ids={"card-a"})
        count_after = self.conn.execute(
            "SELECT COUNT(*) AS c FROM collection_owned_index WHERE display_lang = 'fr'"
        ).fetchone()["c"]
        self.assertEqual(count_after, 1)

        dirty = self.conn.execute("SELECT COUNT(*) AS c FROM collection_index_dirty").fetchone()["c"]
        self.assertEqual(dirty, len(DISPLAY_LANGS))
