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
from mtg_pwa.prices import current_eur_price, extract_eur_prices, parse_price


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
            self.assertTrue(price.is_fallback)

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
            self.assertTrue(summary["price"]["is_fallback"])

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
            self.assertTrue(price.is_fallback)

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


if __name__ == "__main__":
    unittest.main()
