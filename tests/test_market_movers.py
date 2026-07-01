from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_pwa.database import connect, init_db, save_card
from mtg_pwa.server import (
    HistoryBuildOptions,
    cache_market_movers,
    evaluate_speculative_pick,
    get_cached_market_movers,
    market_movers_cache_key,
    market_price_movers,
    select_speculative_picks,
    snapshot_period_bounds,
    speculative_pick_score,
    warm_market_movers_cache,
)


class MarketMoversTest(unittest.TestCase):
    def test_snapshot_period_bounds_uses_price_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "Tracked",
                "prices": {"eur": "2.00"},
            }
            save_card(conn, card)
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    "nonfoil",
                    "2026-06-01",
                    1.0,
                    "mtgjson-cardmarket",
                    "EUR",
                    "2026-06-01T00:00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    "nonfoil",
                    "2026-06-30",
                    2.0,
                    "mtgjson-cardmarket",
                    "EUR",
                    "2026-06-30T00:00:00",
                ),
            )
            conn.commit()

            bounds = snapshot_period_bounds(conn, "cardmarket", "1m")
            conn.close()

            self.assertIsNotNone(bounds)
            assert bounds is not None
            self.assertEqual(bounds, ("2026-06-01", "2026-06-30"))

    def test_market_price_movers_includes_speculative_and_premium_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)

            speculative = {
                "id": "00000000-0000-0000-0000-000000000051",
                "name": "Penny Stock",
                "set": "STX",
                "collector_number": "1",
                "rarity": "rare",
                "prices": {"eur": "2.00"},
            }
            premium = {
                "id": "00000000-0000-0000-0000-000000000052",
                "name": "Premium Staple",
                "set": "MH2",
                "collector_number": "1",
                "rarity": "mythic",
                "prices": {"eur": "20.00"},
            }
            save_card(conn, speculative)
            save_card(conn, premium)

            for card_id, start_price, end_price in (
                (speculative["id"], 1.0, 2.0),
                (premium["id"], 10.0, 20.0),
            ):
                conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (card_id, "nonfoil", "2026-06-01", start_price, "mtgjson-cardmarket", "EUR", "2026-06-01T00:00:00"),
                )
                conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (card_id, "nonfoil", "2026-06-30", end_price, "mtgjson-cardmarket", "EUR", "2026-06-30T00:00:00"),
                )
            conn.commit()

            movers = market_price_movers(conn, "cardmarket", HistoryBuildOptions(), "1m")
            conn.close()

            self.assertEqual(movers["top_speculative_pct_gain"][0]["scryfall_id"], speculative["id"])
            self.assertEqual(movers["top_premium_flat_gain"][0]["scryfall_id"], premium["id"])
            self.assertEqual(movers["top_speculative_picks"][0]["scryfall_id"], speculative["id"])
            self.assertIn("speculative_score", movers["top_speculative_picks"][0])
            self.assertIn("scope", movers)
            self.assertEqual(movers["scope"]["min_release_date"], "2021-04-23")

    def test_market_excludes_pre_strixhaven_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            old_set_card = {
                "id": "00000000-0000-0000-0000-000000000061",
                "name": "Old Card",
                "set": "ZNR",
                "collector_number": "1",
                "rarity": "rare",
                "prices": {"eur": "5.00"},
            }
            save_card(conn, old_set_card)
            for price, snap_date in ((1.0, "2026-06-01"), (3.0, "2026-06-30")):
                conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        old_set_card["id"],
                        "nonfoil",
                        snap_date,
                        price,
                        "mtgjson-cardmarket",
                        "EUR",
                        f"{snap_date}T00:00:00",
                    ),
                )
            conn.commit()

            movers = market_price_movers(conn, "cardmarket", HistoryBuildOptions(), "1m")
            conn.close()

            self.assertEqual(movers["tracked_cards"], 0)
            self.assertEqual(movers["top_flat_gain"], [])

    def test_market_movers_cache_returns_warmed_payload(self) -> None:
        options = HistoryBuildOptions()
        key = market_movers_cache_key("cardmarket", options, "7d")
        self.assertIn("cardmarket", key)

        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000071",
                "name": "Cached Mover",
                "set": "STX",
                "collector_number": "2",
                "rarity": "rare",
                "prices": {"eur": "3.00"},
            }
            save_card(conn, card)
            for price, snap_date in ((1.0, "2026-06-01"), (3.0, "2026-06-30")):
                conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card["id"],
                        "nonfoil",
                        snap_date,
                        price,
                        "mtgjson-cardmarket",
                        "EUR",
                        f"{snap_date}T00:00:00",
                    ),
                )
            conn.commit()

            stats = warm_market_movers_cache(conn, ranges=("7d",))
            cached = get_cached_market_movers("cardmarket", options, "7d")
            conn.close()

            self.assertEqual(stats["ranges_warmed"], 1)
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertGreater(cached["tracked_cards"], 0)
            self.assertEqual(cached, get_cached_market_movers("cardmarket", options, "7d"))


class SpeculativePickScoreTest(unittest.TestCase):
    def test_speculative_pick_score_filters_and_ranks(self) -> None:
        strong = {"start_price": 0.8, "end_price": 2.0, "change_pct": 150.0, "change_flat": 1.2}
        weak_pct = {"start_price": 1.0, "end_price": 1.2, "change_pct": 20.0, "change_flat": 0.2}
        too_expensive_end = {"start_price": 1.0, "end_price": 15.0, "change_pct": 1400.0, "change_flat": 14.0}

        self.assertIsNotNone(speculative_pick_score(strong))
        self.assertIsNone(speculative_pick_score(weak_pct))
        self.assertIsNone(speculative_pick_score(too_expensive_end))

        picks = select_speculative_picks([weak_pct, strong, too_expensive_end])
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["start_price"], 0.8)

    def test_old_stable_spike_scores_higher_than_plain_spike(self) -> None:
        plain = {"start_price": 0.8, "end_price": 2.0, "change_pct": 150.0, "change_flat": 1.2}
        stable_old = dict(plain)
        context = {
            "set_age_years": 5.0,
            "pre_stable": True,
            "breakout": True,
            "pre_min": 0.75,
            "pre_max": 0.85,
        }

        plain_score = speculative_pick_score(plain)
        stable_score = speculative_pick_score(stable_old, context)
        assert plain_score is not None
        assert stable_score is not None
        self.assertGreater(stable_score, plain_score)

        evaluation = evaluate_speculative_pick(stable_old, context)
        assert evaluation is not None
        self.assertIn("ancienne", evaluation["signals"])
        self.assertIn("prix_stable", evaluation["signals"])
        self.assertIn("spike_sur_stabilite", evaluation["signals"])

    def test_select_speculative_picks_uses_pre_period_stability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.sqlite3")
            init_db(conn)
            card = {
                "id": "00000000-0000-0000-0000-000000000081",
                "name": "Stable Old",
                "set": "STX",
                "collector_number": "99",
                "rarity": "rare",
                "prices": {"eur": "2.00"},
            }
            save_card(conn, card)
            for snap_date, price in (
                ("2026-05-01", 0.80),
                ("2026-05-15", 0.82),
                ("2026-05-28", 0.81),
                ("2026-06-01", 0.80),
                ("2026-06-30", 2.00),
            ):
                conn.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id, finish, snapshot_date, price, source, currency, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card["id"],
                        "nonfoil",
                        snap_date,
                        price,
                        "mtgjson-cardmarket",
                        "EUR",
                        f"{snap_date}T00:00:00",
                    ),
                )
            conn.commit()

            movers = [
                {
                    "scryfall_id": card["id"],
                    "start_price": 0.8,
                    "end_price": 2.0,
                    "change_pct": 150.0,
                    "change_flat": 1.2,
                }
            ]
            picks = select_speculative_picks(
                movers,
                conn=conn,
                source_key="cardmarket",
                start_date="2026-06-01",
                as_of_date="2026-06-30",
            )
            conn.close()

            self.assertEqual(len(picks), 1)
            self.assertIn("speculative_signals", picks[0])
            self.assertIn("prix_stable", picks[0]["speculative_signals"])
            self.assertGreater(picks[0]["speculative_score"], 150.0 + 1.2 * 12.0)


if __name__ == "__main__":
    unittest.main()
