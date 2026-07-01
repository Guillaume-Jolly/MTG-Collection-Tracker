from __future__ import annotations

import unittest

from mtg_pwa.database import resolve_display_card_id


class DisplayLangTest(unittest.TestCase):
    def test_resolve_display_card_id_merge_prefers_french(self) -> None:
        card = {"id": "en-id"}
        siblings = {"fr": "fr-id", "en": "en-id"}
        self.assertEqual(resolve_display_card_id(card, siblings, "merge"), "fr-id")

    def test_resolve_display_card_id_merge_falls_back_to_english(self) -> None:
        card = {"id": "en-id"}
        siblings = {"en": "en-id"}
        self.assertEqual(resolve_display_card_id(card, siblings, "merge"), "en-id")

    def test_resolve_display_card_id_french_only(self) -> None:
        card = {"id": "en-id"}
        siblings = {"fr": "fr-id", "en": "en-id"}
        self.assertEqual(resolve_display_card_id(card, siblings, "fr"), "fr-id")


if __name__ == "__main__":
    unittest.main()
