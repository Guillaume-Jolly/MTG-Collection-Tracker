import unittest

from mtg_pwa.server import (
    HistoryBuildOptions,
    deck_history,
    merge_collection_history_points,
    price_on_or_before,
)


class DeckHistoryTest(unittest.TestCase):
    def test_price_on_or_before_uses_latest_known_price(self) -> None:
        dated = {"2026-05-01": 10, "2026-05-15": 12}
        self.assertEqual(price_on_or_before(dated, "2026-05-10"), 10)
        self.assertEqual(price_on_or_before(dated, "2026-05-15"), 12)
        self.assertEqual(price_on_or_before(dated, "2026-05-20"), 12)

    def test_deck_history_carries_prices_forward(self) -> None:
        deck_cards = [{"scryfall_id": "a", "finish": "nonfoil", "quantity": 1}]
        points = [
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-05-01",
                "price": 100.0,
                "source": "mtgjson-cardmarket",
                "currency": "EUR",
            },
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-06-01",
                "price": 80.0,
                "source": "mtgjson-cardmarket",
                "currency": "EUR",
            },
        ]

        history = deck_history(deck_cards, points)

        self.assertEqual([point["snapshot_date"] for point in history], ["2026-05-01", "2026-06-01"])
        self.assertEqual(history[0]["total_eur"], 100.0)
        self.assertEqual(history[1]["total_eur"], 80.0)

    def test_deck_history_supports_non_cardmarket_sources(self) -> None:
        deck_cards = [{"scryfall_id": "a", "finish": "nonfoil", "quantity": 2}]
        points = [
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-06-01",
                "price": 5.5,
                "source": "mtgjson-tcgplayer",
                "currency": "USD",
            }
        ]

        history = deck_history(deck_cards, points)

        self.assertEqual(history[0]["total_eur"], 11.0)

    def test_merge_collection_history_points_prefers_scryfall(self) -> None:
        merged = merge_collection_history_points(
            [
                {
                    "scryfall_id": "a",
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-29",
                    "price": 1.0,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                    "collected_at": "2026-06-20T00:00:00+00:00",
                },
                {
                    "scryfall_id": "a",
                    "finish": "nonfoil",
                    "snapshot_date": "2026-06-29",
                    "price": 2.0,
                    "source": "scryfall-cardmarket",
                    "currency": "EUR",
                    "collected_at": "2026-06-29T12:00:00+00:00",
                },
            ]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["price"], 2.0)
        self.assertEqual(merged[0]["source"], "scryfall-cardmarket")

    def test_deck_history_only_priced_skips_missing_cards(self) -> None:
        deck_cards = [
            {"scryfall_id": "a", "finish": "nonfoil", "quantity": 1},
            {"scryfall_id": "b", "finish": "nonfoil", "quantity": 1},
        ]
        points = [
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-06-01",
                "price": 4.0,
                "source": "mtgjson-cardmarket",
                "currency": "EUR",
            }
        ]

        history = deck_history(deck_cards, points, options=HistoryBuildOptions(only_priced=True))

        self.assertEqual(history[0]["total_eur"], 4.0)
        self.assertEqual(history[0]["priced_cards"], 1)
        self.assertEqual(history[0]["missing_cards"], 0)

    def test_deck_history_nonfoil_mode_uses_nonfoil_snapshots(self) -> None:
        deck_cards = [{"scryfall_id": "a", "finish": "foil", "quantity": 1}]
        points = [
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-06-01",
                "price": 3.0,
                "source": "mtgjson-cardmarket",
                "currency": "EUR",
            }
        ]

        history = deck_history(deck_cards, points, options=HistoryBuildOptions(price_mode="nonfoil"))

    def test_deck_history_uses_live_prices_when_snapshots_missing(self) -> None:
        deck_cards = [
            {"scryfall_id": "a", "finish": "nonfoil", "quantity": 1},
            {"scryfall_id": "b", "finish": "nonfoil", "quantity": 1},
        ]
        points = [
            {
                "scryfall_id": "a",
                "finish": "nonfoil",
                "snapshot_date": "2026-06-01",
                "price": 2.0,
                "source": "mtgjson-cardmarket",
                "currency": "EUR",
            }
        ]
        live_prices = {("b", "nonfoil"): 5}

        history = deck_history(deck_cards, points, live_prices=live_prices)

        self.assertEqual(history[0]["total_eur"], 7.0)
        self.assertEqual(history[0]["priced_cards"], 2)


if __name__ == "__main__":
    unittest.main()
