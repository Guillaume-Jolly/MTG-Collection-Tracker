from __future__ import annotations

import unittest

from mtg_pwa.server import combine_both_price_histories, merge_price_histories, price_history_for_lang_mode


class PriceHistoryLangTest(unittest.TestCase):
    def test_merge_price_histories_prefers_french_on_same_date(self) -> None:
        fr_history = [
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 2.0,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-01",
                "collected_at": "2026-06-01T00:00:00+00:00",
            }
        ]
        en_history = [
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 1.5,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-01",
                "collected_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 1.8,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-15",
                "collected_at": "2026-06-15T00:00:00+00:00",
            },
        ]

        merged = merge_price_histories(fr_history, en_history)

        self.assertEqual(len(merged), 2)
        by_date = {point["snapshot_date"]: point for point in merged}
        self.assertEqual(by_date["2026-06-01"]["price"], 2.0)
        self.assertEqual(by_date["2026-06-01"]["price_lang"], "fr")
        self.assertEqual(by_date["2026-06-15"]["price"], 1.8)
        self.assertEqual(by_date["2026-06-15"]["price_lang"], "en")

    def test_combine_both_price_histories_keeps_parallel_points(self) -> None:
        fr_history = [
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 2.0,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-01",
                "collected_at": "2026-06-01T00:00:00+00:00",
            }
        ]
        en_history = [
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 1.5,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-01",
                "collected_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "currency": "EUR",
                "finish": "nonfoil",
                "price": 1.8,
                "source": "mtgjson-cardmarket",
                "snapshot_date": "2026-06-15",
                "collected_at": "2026-06-15T00:00:00+00:00",
            },
        ]

        combined = combine_both_price_histories(fr_history, en_history)

        self.assertEqual(len(combined), 3)
        june_first = [point for point in combined if point["snapshot_date"] == "2026-06-01"]
        self.assertEqual(len(june_first), 2)
        langs = {point["price_lang"] for point in june_first}
        self.assertEqual(langs, {"fr", "en"})

    def test_price_history_for_lang_mode_uses_english_only(self) -> None:
        class FakeConn:
            def execute(self, *args, **kwargs):
                raise AssertionError("price_history should be patched")

        calls: list[str] = []

        def fake_price_history(conn, scryfall_id, finish) -> list[dict]:
            calls.append(scryfall_id)
            return [{"snapshot_date": "2026-06-01", "price": 1.0, "source": "mtgjson-cardmarket", "currency": "EUR", "finish": finish, "collected_at": "t"}]

        card = {
            "id": "fr-id",
            "lang": "fr",
            "set": "soc",
            "collector_number": "234",
        }
        siblings = {"fr": "fr-id", "en": "en-id"}

        import mtg_pwa.server as server_module

        original_price_history = server_module.price_history
        original_siblings = server_module.language_sibling_ids
        server_module.price_history = fake_price_history
        server_module.language_sibling_ids = lambda conn, current, client=None: siblings
        try:
            history = price_history_for_lang_mode(FakeConn(), card, "nonfoil", "en")
        finally:
            server_module.price_history = original_price_history
            server_module.language_sibling_ids = original_siblings

        self.assertEqual(calls, ["en-id"])
        self.assertEqual(history[0]["price_lang"], "en")

    def test_price_history_for_lang_mode_both_returns_parallel_histories(self) -> None:
        class FakeConn:
            def execute(self, *args, **kwargs):
                raise AssertionError("price_history should be patched")

        def fake_price_history(conn, scryfall_id, finish) -> list[dict]:
            if scryfall_id == "fr-id":
                return [
                    {
                        "snapshot_date": "2026-06-01",
                        "price": 2.0,
                        "source": "mtgjson-cardmarket",
                        "currency": "EUR",
                        "finish": finish,
                        "collected_at": "t-fr",
                    }
                ]
            return [
                {
                    "snapshot_date": "2026-06-01",
                    "price": 1.5,
                    "source": "mtgjson-cardmarket",
                    "currency": "EUR",
                    "finish": finish,
                    "collected_at": "t-en",
                }
            ]

        card = {
            "id": "fr-id",
            "lang": "fr",
            "set": "soc",
            "collector_number": "234",
        }
        siblings = {"fr": "fr-id", "en": "en-id"}

        import mtg_pwa.server as server_module

        original_price_history = server_module.price_history
        original_siblings = server_module.language_sibling_ids
        server_module.price_history = fake_price_history
        server_module.language_sibling_ids = lambda conn, current, client=None: siblings
        try:
            history = price_history_for_lang_mode(FakeConn(), card, "nonfoil", "both")
        finally:
            server_module.price_history = original_price_history
            server_module.language_sibling_ids = original_siblings

        self.assertEqual(len(history), 2)
        langs = {point["price_lang"] for point in history}
        self.assertEqual(langs, {"fr", "en"})


if __name__ == "__main__":
    unittest.main()
