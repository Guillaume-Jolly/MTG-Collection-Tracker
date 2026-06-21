from __future__ import annotations

import io
import unittest

from mtg_pwa.mtgjson import (
    deck_summary,
    extract_price_entry_from_text_stream,
    extract_price_entries_from_text_stream,
    importable_deck_cards,
    market_summaries,
    normalize_price_points,
    sort_decks,
)


class MtgjsonPriceTest(unittest.TestCase):
    def test_extracts_single_uuid_from_all_prices_stream(self) -> None:
        stream = io.StringIO(
            '{"meta":{},"data":{'
            '"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa":{"paper":{"cardmarket":{"currency":"EUR","retail":{"normal":{"2026-01-01":1.0}}}}},'
            '"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb":{"paper":{"tcgplayer":{"currency":"USD","retail":{"foil":{"2026-01-02":2.0}}}}}'
            "}}"
        )

        entry = extract_price_entry_from_text_stream(stream, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        self.assertEqual(entry["paper"]["tcgplayer"]["retail"]["foil"]["2026-01-02"], 2.0)

    def test_extracts_multiple_uuids_from_all_prices_stream(self) -> None:
        stream = io.StringIO(
            '{"meta":{},"data":{'
            '"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa":{"paper":{"cardmarket":{"currency":"EUR","retail":{"normal":{"2026-01-01":1.0}}}}},'
            '"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb":{"paper":{"cardmarket":{"currency":"EUR","retail":{"foil":{"2026-01-02":2.0}}}}},'
            '"cccccccc-cccc-cccc-cccc-cccccccccccc":{"paper":{"tcgplayer":{"currency":"USD","retail":{"normal":{"2026-01-03":3.0}}}}}'
            "}}"
        )

        entries = extract_price_entries_from_text_stream(
            stream,
            {"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "cccccccc-cccc-cccc-cccc-cccccccccccc"},
        )

        self.assertEqual(set(entries), {"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "cccccccc-cccc-cccc-cccc-cccccccccccc"})
        self.assertEqual(entries["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]["paper"]["cardmarket"]["retail"]["normal"]["2026-01-01"], 1.0)

    def test_normalizes_market_points_and_summaries(self) -> None:
        points = normalize_price_points(
            "scryfall-id",
            {
                "paper": {
                    "cardmarket": {
                        "currency": "EUR",
                        "retail": {"normal": {"2026-01-01": 1.25, "2026-01-02": 1.5}},
                    },
                    "tcgplayer": {
                        "currency": "USD",
                        "retail": {"normal": {"2026-01-02": 2.5}, "foil": {"2026-01-02": 5.0}},
                    },
                }
            },
        )

        self.assertEqual(len(points), 4)
        self.assertEqual(points[0]["finish"], "nonfoil")
        self.assertEqual(points[0]["source"], "mtgjson-cardmarket")

        summaries = market_summaries(points, "nonfoil")

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["source"], "mtgjson-cardmarket")
        self.assertEqual(summaries[0]["latest_price"], 1.5)
        self.assertEqual(summaries[0]["point_count"], 2)

    def test_importable_deck_cards_keep_exact_printing_and_finish(self) -> None:
        deck = {
            "name": "Example Precon",
            "code": "EXM",
            "type": "Commander Deck",
            "releaseDate": "2026-01-01",
            "commander": [
                {
                    "count": 1,
                    "name": "Foil Commander",
                    "isFoil": True,
                    "setCode": "EXM",
                    "number": "1",
                    "uuid": "mtgjson-1",
                    "identifiers": {"scryfallId": "scryfall-1"},
                }
            ],
            "mainBoard": [
                {
                    "count": 2,
                    "name": "Normal Card",
                    "isFoil": False,
                    "setCode": "EXM",
                    "number": "2",
                    "uuid": "mtgjson-2",
                    "identifiers": {"scryfallId": "scryfall-2"},
                }
            ],
            "sideBoard": [],
        }

        cards = importable_deck_cards(deck)
        summary = deck_summary(deck, "ExamplePrecon_EXM")

        self.assertEqual(cards[0]["finish"], "foil")
        self.assertEqual(cards[0]["scryfall_id"], "scryfall-1")
        self.assertEqual(cards[1]["quantity"], 2)
        self.assertEqual(cards[1]["finish"], "nonfoil")
        self.assertEqual(summary["card_count"], 3)
        self.assertEqual(summary["foil_count"], 1)

    def test_sort_decks_by_extension_and_release_date(self) -> None:
        decks = [
            {"code": "FIC", "name": "B", "releaseDate": "2025-06-13"},
            {"code": "CMM", "name": "A", "releaseDate": "2023-08-04"},
            {"code": "FIC", "name": "A", "releaseDate": "2025-06-13"},
        ]

        by_extension = sort_decks(decks, "extension")
        by_recent = sort_decks(decks, "release_desc")

        self.assertEqual([deck["code"] for deck in by_extension], ["CMM", "FIC", "FIC"])
        self.assertEqual([deck["name"] for deck in by_recent[:2]], ["B", "A"])


if __name__ == "__main__":
    unittest.main()
