from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from mtg_pwa.database import adjust_collection_quantity, connect, init_db, save_card
from mtg_pwa.server import (
    HistoryBuildOptions,
    collection_price_movers,
    deck_history,
    filter_cards_excluding_new_on_period,
    history_period_bounds,
)


class CollectionMoversTest(unittest.TestCase):
    def test_history_period_bounds_matches_chart_window(self) -> None:
        history = [
            {"snapshot_date": "2026-06-01", "total_eur": 10.0},
            {"snapshot_date": "2026-06-15", "total_eur": 12.0},
            {"snapshot_date": "2026-06-30", "total_eur": 11.0},
        ]

        start, end = history_period_bounds(history, "1m")

        self.assertEqual(end, "2026-06-30")
        self.assertEqual(start, "2026-06-01")

    def test_collection_price_movers_excludes_zero_price_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)

            winner = {
                "id": "00000000-0000-0000-0000-000000000021",
                "name": "Winner",
                "prices": {"eur": "4.00"},
            }
            loser = {
                "id": "00000000-0000-0000-0000-000000000022",
                "name": "Loser",
                "prices": {"eur": "2.00"},
            }
            from_zero = {
                "id": "00000000-0000-0000-0000-000000000023",
                "name": "From Zero",
                "prices": {"eur": "1.00"},
            }
            save_card(conn, winner)
            save_card(conn, loser)
            save_card(conn, from_zero)
            adjust_collection_quantity(conn, scryfall_id=winner["id"], finish="nonfoil", delta=1)
            adjust_collection_quantity(conn, scryfall_id=loser["id"], finish="nonfoil", delta=1)
            adjust_collection_quantity(conn, scryfall_id=from_zero["id"], finish="nonfoil", delta=1)

            points = [
                {
                    "scryfall_id": winner["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-01",
                    "price": 1.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": winner["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 4.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": loser["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-01",
                    "price": 4.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": loser["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 2.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": from_zero["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 1.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
            ]
            collection_cards = [
                {"scryfall_id": winner["id"], "finish": "nonfoil", "quantity": 1, "_card": winner},
                {"scryfall_id": loser["id"], "finish": "nonfoil", "quantity": 1, "_card": loser},
                {"scryfall_id": from_zero["id"], "finish": "nonfoil", "quantity": 1, "_card": from_zero},
            ]
            history = deck_history(collection_cards, points)
            movers = collection_price_movers(
                conn,
                collection_cards,
                points,
                {},
                HistoryBuildOptions(),
                history,
                "1m",
                currency="EUR",
            )
            conn.close()

            self.assertEqual(movers["top_flat_gain"][0]["scryfall_id"], winner["id"])
            self.assertEqual(movers["top_flat_loss"][0]["scryfall_id"], loser["id"])
            ranked_ids = {
                item["scryfall_id"]
                for bucket in (
                    movers["top_flat_gain"],
                    movers["top_flat_loss"],
                    movers["top_pct_gain"],
                    movers["top_pct_loss"],
                )
                for item in bucket
            }
            self.assertNotIn(from_zero["id"], ranked_ids)

    def test_collection_price_movers_excludes_by_rarity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)

            common = {
                "id": "00000000-0000-0000-0000-000000000041",
                "name": "Common",
                "rarity": "common",
                "prices": {"eur": "1.00"},
            }
            mythic = {
                "id": "00000000-0000-0000-0000-000000000042",
                "name": "Mythic",
                "rarity": "mythic",
                "prices": {"eur": "20.00"},
            }
            save_card(conn, common)
            save_card(conn, mythic)
            adjust_collection_quantity(conn, scryfall_id=common["id"], finish="nonfoil", delta=1)
            adjust_collection_quantity(conn, scryfall_id=mythic["id"], finish="nonfoil", delta=1)

            points = [
                {
                    "scryfall_id": common["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-01",
                    "price": 1.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": common["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 3.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": mythic["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-01",
                    "price": 10.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": mythic["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 20.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
            ]
            collection_cards = [
                {"scryfall_id": common["id"], "finish": "nonfoil", "quantity": 1, "_card": common},
                {"scryfall_id": mythic["id"], "finish": "nonfoil", "quantity": 1, "_card": mythic},
            ]
            history = deck_history(collection_cards, points)
            movers = collection_price_movers(
                conn,
                collection_cards,
                points,
                {},
                HistoryBuildOptions(exclude_movers_common=True),
                history,
                "1m",
                currency="EUR",
            )
            conn.close()

            self.assertEqual(movers["excluded_by_rarity"], 1)
            self.assertEqual(movers["top_flat_gain"][0]["scryfall_id"], mythic["id"])
            ranked_ids = {
                item["scryfall_id"]
                for bucket in (
                    movers["top_flat_gain"],
                    movers["top_flat_loss"],
                    movers["top_pct_gain"],
                    movers["top_pct_loss"],
                )
                for item in bucket
            }
            self.assertNotIn(common["id"], ranked_ids)

    def test_filter_cards_excluding_new_on_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)

            stable = {
                "id": "00000000-0000-0000-0000-000000000031",
                "name": "Stable",
                "prices": {"eur": "2.00"},
            }
            new_card = {
                "id": "00000000-0000-0000-0000-000000000032",
                "name": "New",
                "prices": {"eur": "1.00"},
            }
            save_card(conn, stable)
            save_card(conn, new_card)

            points = [
                {
                    "scryfall_id": stable["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-01",
                    "price": 2.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": stable["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 2.5,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
                {
                    "scryfall_id": new_card["id"],
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-30",
                    "price": 1.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                },
            ]
            collection_cards = [
                {"scryfall_id": stable["id"], "finish": "nonfoil", "quantity": 1, "_card": stable},
                {"scryfall_id": new_card["id"], "finish": "nonfoil", "quantity": 1, "_card": new_card},
            ]
            history = deck_history(collection_cards, points)
            filtered = filter_cards_excluding_new_on_period(
                collection_cards,
                points,
                {},
                HistoryBuildOptions(exclude_new_cards=True),
                history,
                "1m",
            )
            conn.close()

            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["scryfall_id"], stable["id"])


if __name__ == "__main__":
    unittest.main()
