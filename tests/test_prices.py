from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from mtg_pwa.database import (
    card_summary,
    connect,
    display_price_for,
    init_db,
    latest_snapshot,
    price_periods,
    save_card,
    save_fallback_price_snapshot,
    save_price_snapshots,
)
from mtg_pwa.prices import (
    FINISH_DUPLICATED_SOURCE,
    available_finishes_for_card,
    current_eur_price,
    display_finishes_for_card,
    extract_eur_prices,
    parse_price,
)


class PriceSelectionTest(unittest.TestCase):
    def test_parse_price_accepts_scryfall_strings(self) -> None:
        self.assertEqual(parse_price("12.34"), Decimal("12.34"))
        self.assertIsNone(parse_price(None))
        self.assertIsNone(parse_price(""))

    def test_extracts_eur_prices_by_finish(self) -> None:
        card = {
            "prices": {
                "eur": "1.20",
                "eur_foil": "2.40",
                "eur_etched": None,
                "usd": "1.99",
            }
        }

        self.assertEqual(
            extract_eur_prices(card),
            {"nonfoil": Decimal("1.20"), "foil": Decimal("2.40")},
        )

    def test_available_finishes_merges_scryfall_prices_and_collection(self) -> None:
        card = {
            "finishes": ["nonfoil"],
            "prices": {"eur": "1.20", "eur_foil": "2.40"},
        }

        finishes = available_finishes_for_card(card, extra_finishes=["etched"])

        self.assertEqual(finishes, ["nonfoil", "foil", "etched"])

    def test_current_price_uses_requested_finish(self) -> None:
        card = {"prices": {"eur": "1.20", "eur_foil": "2.40"}}

        price = current_eur_price(card, "foil")

        self.assertIsNotNone(price)
        assert price is not None
        self.assertEqual(price.price, Decimal("2.40"))
        self.assertEqual(price.source, "scryfall-cardmarket")
        self.assertFalse(price.is_fallback)

    def test_display_price_falls_back_to_latest_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card_with_price = {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "Test Card",
                "prices": {"eur": "3.50"},
            }
            save_card(conn, card_with_price)
            save_price_snapshots(conn, card_with_price)
            conn.commit()

            card_without_price = {
                "id": card_with_price["id"],
                "name": "Test Card",
                "prices": {"eur": None},
            }

            price = display_price_for(conn, card_without_price, "nonfoil")

            self.assertIsNotNone(price)
            assert price is not None
            self.assertEqual(price.price, Decimal("3.5"))
            self.assertFalse(price.is_fallback)
            conn.close()

    def test_card_summary_marks_fallback_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000002",
                "name": "Fallback Card",
                "prices": {"eur": "4.00"},
            }
            save_card(conn, card)
            save_price_snapshots(conn, card)
            conn.commit()

            cached = latest_snapshot(conn, card["id"], "nonfoil")
            self.assertIsNotNone(cached)

            summary = card_summary(
                conn,
                {"id": card["id"], "name": "Fallback Card", "prices": {"eur": None}},
                "nonfoil",
            )

            self.assertEqual(summary["price"]["price"], 4.0)
            self.assertFalse(summary["price"]["is_fallback"])
            conn.close()

    def test_card_summary_uses_available_finish_when_requested_finish_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            serialized_card = {
                "id": "00000000-0000-0000-0000-000000000004",
                "name": "Serialized Card",
                "finishes": ["foil"],
                "prices": {"eur": None, "eur_foil": "78.17"},
            }
            save_card(conn, serialized_card)
            save_price_snapshots(conn, serialized_card)
            conn.commit()

            summary = card_summary(conn, serialized_card, "nonfoil")

            self.assertEqual(summary["display_finish"], "foil")
            self.assertEqual(summary["price"]["finish"], "foil")
            self.assertEqual(summary["price"]["price"], 78.17)
            conn.close()

    def test_fallback_snapshot_can_use_english_print_price_for_localized_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            localized_card = {
                "id": "00000000-0000-0000-0000-000000000003",
                "name": "Key to the City",
                "printed_name": "Cle de la ville",
                "lang": "fr",
                "prices": {"eur": None},
            }
            save_card(conn, localized_card)
            save_fallback_price_snapshot(
                conn,
                scryfall_id=localized_card["id"],
                finish="nonfoil",
                price=Decimal("0.26"),
                source="scryfall-cardmarket-en-print:test",
            )
            conn.commit()

            price = display_price_for(conn, localized_card, "nonfoil")

            self.assertIsNotNone(price)
            assert price is not None
            self.assertEqual(price.price, Decimal("0.26"))
            self.assertFalse(price.is_fallback)
            self.assertIn("en-print", price.source)
            conn.close()

    def test_price_periods_are_unavailable_when_history_is_too_short(self) -> None:
        history = [
            {
                "currency": "EUR",
                "finish": "foil",
                "price": 78.17,
                "source": "scryfall-cardmarket",
                "snapshot_date": "2026-06-21",
                "collected_at": "2026-06-21T05:00:00+00:00",
            }
        ]

        periods = price_periods(history)

        self.assertEqual([period["key"] for period in periods], ["1d", "1m", "6m", "1y", "5y"])
        self.assertFalse(any(period["available"] for period in periods))
        self.assertEqual(periods[0]["first_available_date"], "2026-06-21")
        self.assertEqual(periods[0]["end_price"], 78.17)

    def test_price_periods_only_available_when_requested_window_is_covered(self) -> None:
        history = [
            {
                "currency": "EUR",
                "finish": "foil",
                "price": 70.0,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-01-21",
                "collected_at": "2026-06-21T05:00:00+00:00",
            },
            {
                "currency": "EUR",
                "finish": "foil",
                "price": 78.17,
                "source": "scryfall-cardmarket",
                "snapshot_date": "2026-06-21",
                "collected_at": "2026-06-21T05:00:00+00:00",
            },
        ]

        periods = {period["key"]: period for period in price_periods(history)}

        self.assertTrue(periods["1m"]["available"])
        self.assertFalse(periods["6m"]["available"])
        self.assertFalse(periods["1y"]["available"])
        self.assertFalse(periods["5y"]["available"])


    def test_card_summary_always_shows_foil_with_na_when_cardmarket_phantom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            from mtg_pwa.database import cardmarket_product_insights, save_cardmarket_price_guide_daily

            card = {
                "id": "00000000-0000-0000-0000-000000000010",
                "name": "Aboleth Spawn",
                "finishes": ["nonfoil"],
                "prices": {"eur": "8.25"},
            }
            save_card(conn, card)
            save_price_snapshots(conn, card)
            conn.execute(
                """
                INSERT INTO cardmarket_product_map (
                    id_product, scryfall_id, set_code, collector_number, mapped_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (661288, card["id"], "CLB", "662", "2026-07-08T00:00:00+00:00"),
            )
            save_cardmarket_price_guide_daily(
                conn,
                [
                    {
                        "id_product": 661288,
                        "snapshot_date": "2026-07-08",
                        "trend": 8.25,
                        "trend_foil": 3.5,
                        "avg7": 8.29,
                        "avg7_foil": 3.5,
                        "low_price": 7.0,
                        "low_foil": None,
                        "avg": 8.53,
                        "avg_foil": None,
                        "guide_version": 1,
                        "guide_created_at": "2026-07-08",
                        "collected_at": "2026-07-08T00:00:00+00:00",
                    }
                ],
            )
            conn.commit()

            summary = card_summary(conn, card, "nonfoil")
            insights = cardmarket_product_insights(conn, card)

            self.assertEqual(summary["available_finishes"], ["nonfoil", "foil"])
            self.assertTrue(summary["prices_by_finish"]["foil"]["unavailable"])
            self.assertEqual(summary["prices_by_finish"]["foil"]["unavailable_reason"], "cardmarket-no-stock")
            self.assertEqual(summary["foil_availability"]["status"], "unavailable")
            self.assertIsNotNone(insights)
            assert insights is not None
            self.assertEqual(insights["foil_status"], "unavailable")
            self.assertIsNone(insights["foil"])
            conn.close()

    def test_card_summary_includes_foil_when_scryfall_declares_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000012",
                "name": "Real Foil Card",
                "finishes": ["nonfoil", "foil"],
                "prices": {"eur": "2.00", "eur_foil": "4.00"},
            }
            save_card(conn, card)
            save_price_snapshots(conn, card)
            conn.commit()

            summary = card_summary(conn, card, "nonfoil")

            self.assertEqual(summary["available_finishes"], ["nonfoil", "foil"])
            self.assertEqual(summary["prices_by_finish"]["foil"]["price"], 4.0)
            conn.close()

    def test_card_summary_duplicates_nonfoil_price_for_foil_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000011",
                "name": "Only Nonfoil",
                "finishes": ["nonfoil", "foil"],
                "prices": {"eur": "2.00"},
            }
            save_card(conn, card)
            save_price_snapshots(conn, card)
            conn.commit()

            summary = card_summary(conn, card, "nonfoil")

            self.assertEqual(summary["available_finishes"], ["nonfoil", "foil"])
            self.assertEqual(summary["prices_by_finish"]["foil"]["price"], 2.0)
            self.assertEqual(
                summary["prices_by_finish"]["foil"]["source"],
                "scryfall-cardmarket-finish-duplicated",
            )
            self.assertEqual(summary["prices_by_finish"]["foil"]["duplicate_from_finish"], "nonfoil")
            conn.close()

    def test_card_summary_uses_pure_scryfall_price_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000013",
                "name": "Pure Price Card",
                "finishes": ["nonfoil", "foil"],
                "prices": {"eur": "5.00"},
            }
            save_card(conn, card)
            save_price_snapshots(conn, card)
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, currency, finish, price, source, snapshot_date,
                    collected_at, source_updated_at
                )
                VALUES (?, 'EUR', 'foil', ?, 'mtgjson-cardmarket', '2026-07-08', ?, NULL)
                """,
                (card["id"], 12.0, "2026-07-08T00:00:00+00:00"),
            )
            conn.commit()

            summary = card_summary(conn, card, "nonfoil")

            self.assertEqual(summary["available_finishes"], ["nonfoil", "foil"])
            self.assertEqual(summary["prices_by_finish"]["foil"]["price"], 5.0)
            self.assertEqual(summary["prices_by_finish"]["foil"]["source"], FINISH_DUPLICATED_SOURCE)
            conn.close()

    def test_display_finishes_always_includes_foil(self) -> None:
        card = {"finishes": ["nonfoil"]}
        self.assertEqual(display_finishes_for_card(card), ["nonfoil", "foil"])
        etched_card = {"finishes": ["nonfoil", "etched"]}
        self.assertEqual(display_finishes_for_card(etched_card), ["nonfoil", "foil", "etched"])
        foil_only = {"finishes": ["foil"], "prices": {"eur_foil": "10.00"}}
        self.assertEqual(display_finishes_for_card(foil_only), ["foil"])

    def test_cardmarket_foil_row_is_phantom_without_stock(self) -> None:
        from mtg_pwa.database import cardmarket_foil_row_is_phantom

        self.assertTrue(
            cardmarket_foil_row_is_phantom(
                {
                    "trend_foil": 3.5,
                    "low_foil": None,
                    "avg_foil": None,
                    "avg7_foil": 3.5,
                }
            )
        )
        self.assertFalse(
            cardmarket_foil_row_is_phantom(
                {
                    "trend_foil": 3.5,
                    "low_foil": 2.99,
                    "avg_foil": None,
                }
            )
        )

    def test_cardmarket_product_insights_ignores_phantom_foil(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            from mtg_pwa.database import cardmarket_product_insights, save_cardmarket_price_guide_daily

            card = {
                "id": "00000000-0000-0000-0000-000000000014",
                "name": "Aboleth",
                "finishes": ["nonfoil"],
            }
            save_card(conn, card)
            conn.execute(
                """
                INSERT INTO cardmarket_product_map (
                    id_product, scryfall_id, set_code, collector_number, mapped_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (661288, card["id"], "CLB", "662", "2026-07-08T00:00:00+00:00"),
            )
            save_cardmarket_price_guide_daily(
                conn,
                [
                    {
                        "id_product": 661288,
                        "snapshot_date": "2026-07-08",
                        "trend": 8.25,
                        "trend_foil": 3.5,
                        "avg7": 8.29,
                        "avg7_foil": 3.5,
                        "low_price": 7.0,
                        "low_foil": None,
                        "avg": 8.53,
                        "avg_foil": None,
                        "guide_version": 1,
                        "guide_created_at": "2026-07-08",
                        "collected_at": "2026-07-08T00:00:00+00:00",
                    }
                ],
            )
            conn.commit()

            insights = cardmarket_product_insights(conn, card)

            self.assertIsNotNone(insights)
            assert insights is not None
            self.assertIsNone(insights["foil"])
            self.assertEqual(insights["foil_status"], "unavailable")
            self.assertEqual(insights["nonfoil"]["trend"], 8.25)
            conn.close()

    def test_latest_snapshot_prefers_scryfall_over_mtgjson(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card_id = "00000000-0000-0000-0000-000000000099"
            save_card(conn, {"id": card_id, "name": "Snapshot Card", "prices": {"eur": None}})
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, currency, finish, price, source, snapshot_date,
                    collected_at, source_updated_at
                )
                VALUES (?, 'EUR', 'nonfoil', ?, 'mtgjson-cardmarket', '2026-06-29', ?, NULL)
                """,
                (card_id, 1.0, "2026-06-29T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, currency, finish, price, source, snapshot_date,
                    collected_at, source_updated_at
                )
                VALUES (?, 'EUR', 'nonfoil', ?, 'scryfall-cardmarket', '2026-06-29', ?, NULL)
                """,
                (card_id, 2.5, "2026-06-29T12:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            conn = connect(Path(tmp) / "test.sqlite3")
            price = latest_snapshot(conn, card_id, "nonfoil")
            conn.close()

            self.assertIsNotNone(price)
            assert price is not None
            self.assertEqual(price.price, Decimal("2.5"))
            self.assertEqual(price.source, "scryfall-cardmarket")
            self.assertFalse(price.is_fallback)


if __name__ == "__main__":
    unittest.main()
