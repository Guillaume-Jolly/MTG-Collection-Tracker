from __future__ import annotations

import unittest

from mtg_pwa.scryfall import normalize_search_query


class ScryfallQueryTest(unittest.TestCase):
    def test_plain_query_searches_card_name(self) -> None:
        self.assertEqual(normalize_search_query("Sol Ring"), 'name:"Sol Ring"')

    def test_advanced_query_is_preserved(self) -> None:
        self.assertEqual(normalize_search_query("type:dragon color:r"), "type:dragon color:r")
        self.assertEqual(normalize_search_query('!"Sol Ring"'), '!"Sol Ring"')


if __name__ == "__main__":
    unittest.main()
