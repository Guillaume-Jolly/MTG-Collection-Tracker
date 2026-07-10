import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mtg_pwa.database import build_language_siblings_for_collectors, connect, init_db, save_card
from mtg_pwa.sets_catalog import (
    invalidate_owned_collection_cache,
    list_owned_collection_cards,
    merged_owned_collection_cards,
)


class MyCollectionPaginationTest(unittest.TestCase):
    def test_list_owned_collection_cards_paginates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            for index in range(5):
                save_card(
                    conn,
                    {
                        "id": f"00000000-0000-0000-0000-00000000000{index}",
                        "name": f"Card {index}",
                        "set": "tst",
                        "collector_number": str(index),
                        "finishes": ["nonfoil"],
                        "prices": {"eur": "1.00"},
                    },
                )
                conn.execute(
                    """
                    INSERT INTO collection_items (
                        scryfall_id, quantity, finish, condition, language,
                        purchase_currency, created_at, updated_at
                    )
                    VALUES (?, 1, 'nonfoil', 'near_mint', 'en', 'EUR', '2026-01-01', '2026-01-01')
                    """,
                    (f"00000000-0000-0000-0000-00000000000{index}",),
                )
            conn.commit()
            invalidate_owned_collection_cache()

            page = list_owned_collection_cards(conn, limit=50, offset=0)
            self.assertEqual(page["pagination"]["total"], 5)
            self.assertEqual(page["pagination"]["page_size"], 50)
            self.assertEqual(len(page["cards"]), 5)
            conn.close()

    def test_merged_owned_collection_cache_reuses_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            save_card(
                conn,
                {
                    "id": "00000000-0000-0000-0000-000000000099",
                    "name": "Cached Card",
                    "set": "tst",
                    "collector_number": "1",
                    "finishes": ["nonfoil"],
                    "prices": {"eur": "2.00"},
                },
            )
            conn.execute(
                """
                INSERT INTO collection_items (
                    scryfall_id, quantity, finish, condition, language,
                    purchase_currency, created_at, updated_at
                )
                VALUES (?, 1, 'nonfoil', 'near_mint', 'en', 'EUR', '2026-01-01', '2026-01-01')
                """,
                ("00000000-0000-0000-0000-000000000099",),
            )
            conn.commit()
            invalidate_owned_collection_cache()
            first = merged_owned_collection_cards(conn)
            second = merged_owned_collection_cards(conn)
            self.assertEqual(len(first), len(second))
            conn.close()

    def test_fr_display_lang_skips_bulk_siblings_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            save_card(
                conn,
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "Lightning Bolt",
                    "printed_name": "Éclair",
                    "lang": "fr",
                    "set": "lea",
                    "collector_number": "161",
                    "finishes": ["nonfoil"],
                    "prices": {"eur": "1.00"},
                },
            )
            conn.execute(
                """
                INSERT INTO collection_items (
                    scryfall_id, quantity, finish, condition, language,
                    purchase_currency, created_at, updated_at
                )
                VALUES (?, 1, 'nonfoil', 'near_mint', 'fr', 'EUR', '2026-01-01', '2026-01-01')
                """,
                ("00000000-0000-0000-0000-000000000001",),
            )
            conn.commit()
            invalidate_owned_collection_cache()

            with patch("mtg_pwa.sets_catalog.build_set_language_siblings") as bulk_siblings:
                cards = merged_owned_collection_cards(conn, display_lang="fr")
                bulk_siblings.assert_not_called()

            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]["lang"], "fr")
            conn.close()

    def test_en_display_lang_lazy_sibling_lookup_for_wrong_lang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            save_card(
                conn,
                {
                    "id": "00000000-0000-0000-0000-000000000010",
                    "name": "Lightning Bolt",
                    "lang": "en",
                    "set": "lea",
                    "collector_number": "161",
                    "finishes": ["nonfoil"],
                    "prices": {"eur": "1.00"},
                },
            )
            save_card(
                conn,
                {
                    "id": "00000000-0000-0000-0000-000000000011",
                    "name": "Lightning Bolt",
                    "printed_name": "Éclair",
                    "lang": "fr",
                    "set": "lea",
                    "collector_number": "161",
                    "finishes": ["nonfoil"],
                    "prices": {"eur": "1.00"},
                },
            )
            conn.execute(
                """
                INSERT INTO collection_items (
                    scryfall_id, quantity, finish, condition, language,
                    purchase_currency, created_at, updated_at
                )
                VALUES (?, 1, 'nonfoil', 'near_mint', 'en', 'EUR', '2026-01-01', '2026-01-01')
                """,
                ("00000000-0000-0000-0000-000000000010",),
            )
            conn.commit()
            invalidate_owned_collection_cache()

            with patch("mtg_pwa.sets_catalog.build_set_language_siblings") as bulk_siblings:
                cards = merged_owned_collection_cards(conn, display_lang="fr")
                bulk_siblings.assert_not_called()

            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]["lang"], "fr")
            self.assertEqual(cards[0]["printed_name"], "Éclair")
            conn.close()

    def test_batch_language_siblings_for_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            for card_id, lang, printed in (
                ("00000000-0000-0000-0000-000000000010", "en", None),
                ("00000000-0000-0000-0000-000000000011", "fr", "Éclair"),
            ):
                save_card(
                    conn,
                    {
                        "id": card_id,
                        "name": "Lightning Bolt",
                        "printed_name": printed,
                        "lang": lang,
                        "set": "lea",
                        "collector_number": "161",
                        "finishes": ["nonfoil"],
                        "prices": {"eur": "1.00"},
                    },
                )
            siblings = build_language_siblings_for_collectors(conn, {"lea": {"161"}})
            self.assertEqual(
                siblings[("lea", "161")],
                {
                    "en": "00000000-0000-0000-0000-000000000010",
                    "fr": "00000000-0000-0000-0000-000000000011",
                },
            )
            conn.close()

    def test_list_owned_collection_enriches_only_current_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            for index in range(55):
                save_card(
                    conn,
                    {
                        "id": f"00000000-0000-0000-0000-00000000{index:04d}",
                        "name": f"Card {index}",
                        "set": "tst",
                        "collector_number": str(index),
                        "finishes": ["nonfoil"],
                        "prices": {"eur": "1.00"},
                    },
                )
                conn.execute(
                    """
                    INSERT INTO collection_items (
                        scryfall_id, quantity, finish, condition, language,
                        purchase_currency, created_at, updated_at
                    )
                    VALUES (?, 1, 'nonfoil', 'near_mint', 'en', 'EUR', '2026-01-01', '2026-01-01')
                    """,
                    (f"00000000-0000-0000-0000-00000000{index:04d}",),
                )
            conn.commit()
            invalidate_owned_collection_cache()

            with patch("mtg_pwa.sets_catalog.display_price_for") as live_prices:
                live_prices.return_value = None
                page = list_owned_collection_cards(conn, limit=50, offset=0)
                self.assertEqual(len(page["cards"]), 50)
                self.assertEqual(page["pagination"]["total"], 55)
                self.assertLessEqual(live_prices.call_count, 50)
            conn.close()


if __name__ == "__main__":
    unittest.main()
