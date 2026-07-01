from mtg_pwa.database import finish_breakdown_for_scryfall, oracle_collection_summary
from mtg_pwa.sets_catalog import (
    card_sort_value,
    card_type_parts,
    collection_group_for,
    is_secret_lair_set,
    is_universes_beyond_set,
    merge_owned_cards_by_scryfall,
    mtgjson_card_to_payload,
    sort_cards,
)


def test_secret_lair_detects_parent_and_codes():
    assert is_secret_lair_set({"code": "SLD", "name": "Secret Lair Drop", "type": "box"})
    assert is_secret_lair_set({"code": "SLC", "parentCode": "SLD", "name": "Secret Lair Countdown"})
    assert not is_secret_lair_set({"code": "SLCI", "parentCode": "LCI", "name": "Substitute Cards"})


def test_universes_beyond_detects_roots_and_commander_children():
    assert is_universes_beyond_set({"code": "FIN", "type": "expansion", "name": "Final Fantasy"})
    assert is_universes_beyond_set({"code": "FIC", "parentCode": "FIN", "type": "commander"})
    assert is_universes_beyond_set({"code": "TRK", "type": "expansion", "name": "Star Trek"})
    assert is_universes_beyond_set({"code": "TRC", "parentCode": "TRK", "type": "commander"})
    assert not is_universes_beyond_set({"code": "AFIN", "parentCode": "FIN", "type": "memorabilia"})


def test_collection_group_priority():
    assert collection_group_for({"code": "SLD", "name": "Secret Lair Drop"}) == "secret_lair"
    assert collection_group_for({"code": "FIN", "type": "expansion"}) == "universes_beyond"
    assert collection_group_for({"code": "MKM", "type": "expansion"}) is None


def test_card_type_parts():
    assert card_type_parts("Creature — Human Wizard") == ("creature", "human wizard")
    assert card_type_parts("Artifact") == ("artifact", "")


def test_owned_card_sorting():
    cards = [
        {"name": "Zebra", "cmc": 3, "quantity": 1},
        {"name": "Alpha", "cmc": 1, "quantity": 2},
        {"name": "Beta", "cmc": 5, "quantity": 1},
    ]
    sort_cards(cards, "name_asc")
    assert [card["name"] for card in cards] == ["Alpha", "Beta", "Zebra"]
    sort_cards(cards, "cmc_desc,name_asc")
    assert [card["name"] for card in cards] == ["Beta", "Zebra", "Alpha"]
    assert card_sort_value({"colors": ["U", "W"]}, "color") == "UW"

    owned_cards = [
        {"name": "Missing", "owned": False, "quantity": 0},
        {"name": "Owned", "owned": True, "quantity": 2},
        {"name": "Also missing", "owned": False, "quantity": 0},
    ]
    sort_cards(owned_cards, "owned_desc")
    assert [card["name"] for card in owned_cards] == ["Owned", "Also missing", "Missing"]
    sort_cards(owned_cards, "owned_asc")
    assert [card["name"] for card in owned_cards] == ["Also missing", "Missing", "Owned"]


def test_merge_owned_cards_by_scryfall():
    cards = [
        {
            "scryfall_id": "abc",
            "finish": "nonfoil",
            "quantity": 2,
            "name": "Bolt",
            "line_value_eur": 1.0,
        },
        {
            "scryfall_id": "abc",
            "finish": "foil",
            "quantity": 1,
            "name": "Bolt",
            "line_value_eur": 2.0,
        },
        {
            "scryfall_id": "def",
            "finish": "nonfoil",
            "quantity": 1,
            "name": "Island",
            "line_value_eur": 0.5,
        },
    ]
    merged = merge_owned_cards_by_scryfall(cards)
    assert len(merged) == 2
    bolt = next(card for card in merged if card["scryfall_id"] == "abc")
    assert bolt["quantity"] == 3
    assert bolt["finish_breakdown"] == {"nonfoil": 2, "foil": 1}
    assert bolt["finish"] == "nonfoil"
    assert bolt["line_value_eur"] == 3.0


def test_mtgjson_card_to_payload_uses_exact_scryfall_finish_breakdown():
    owned_by_finish = {
        ("card-a", "nonfoil"): 1,
        ("card-a", "foil"): 2,
        ("card-b", "nonfoil"): 3,
    }
    payload = mtgjson_card_to_payload(
        {"identifiers": {"scryfallId": "card-a"}, "finishes": ["nonfoil", "foil"]},
        {},
        owned_by_finish=owned_by_finish,
    )
    assert payload["quantity"] == 3
    assert payload["finish_breakdown"] == {"nonfoil": 1, "foil": 2}
    assert payload["finish"] == "nonfoil"

    other = mtgjson_card_to_payload(
        {"identifiers": {"scryfallId": "card-b"}, "finishes": ["nonfoil"]},
        {},
        owned_by_finish=owned_by_finish,
    )
    assert other["quantity"] == 3
    assert other["finish_breakdown"] == {"nonfoil": 3}


def test_finish_breakdown_for_scryfall_ignores_other_printings():
    owned_by_finish = {
        ("reprint-a", "nonfoil"): 2,
        ("reprint-b", "foil"): 4,
    }
    assert finish_breakdown_for_scryfall(owned_by_finish, "reprint-a") == {"nonfoil": 2}
    assert finish_breakdown_for_scryfall(owned_by_finish, "reprint-b") == {"foil": 4}


def test_oracle_collection_summary_counts_all_printings():
    import json
    import tempfile
    from pathlib import Path

    from mtg_pwa.database import connect, init_db, save_card

    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "test.sqlite3")
        init_db(conn)
        cards = [
            {
                "id": "00000000-0000-0000-0000-000000000011",
                "oracle_id": "oracle-1",
                "name": "Bolt",
                "set": "M10",
                "collector_number": "1",
            },
            {
                "id": "00000000-0000-0000-0000-000000000012",
                "oracle_id": "oracle-1",
                "name": "Bolt",
                "set": "M11",
                "collector_number": "1",
            },
        ]
        for card in cards:
            save_card(conn, card)
        conn.execute(
            """
            INSERT INTO collection_items (
                scryfall_id, quantity, finish, condition, purchase_currency, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cards[0]["id"],
                2,
                "nonfoil",
                "near_mint",
                "EUR",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO collection_items (
                scryfall_id, quantity, finish, condition, purchase_currency, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cards[1]["id"],
                1,
                "foil",
                "near_mint",
                "EUR",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
        conn.commit()

        summary = oracle_collection_summary(conn, "oracle-1")
        conn.close()

        assert summary is not None
        assert summary["total_copies"] == 3
        assert summary["printing_count"] == 2
        assert summary["by_finish"] == {"nonfoil": 2, "foil": 1}
