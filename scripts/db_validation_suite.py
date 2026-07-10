#!/usr/bin/env python3
"""Validation 10 cartes + benchmarks avant/apres optimisation BDD."""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import (  # noqa: E402
    DEFAULT_DB_PATH,
    cardmarket_latest_guide_for_card,
    connect,
    display_price_for,
    get_cached_card,
    init_db,
    price_history,
)
from mtg_pwa.sets_catalog import market_eligible_set_codes  # noqa: E402

RESULTS_DIR = REPO_ROOT / "data" / "validation_runs"


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def pick_samples(conn, *, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    owned = [
        row["scryfall_id"]
        for row in conn.execute(
            "SELECT DISTINCT scryfall_id FROM collection_items WHERE quantity > 0"
        ).fetchall()
    ]
    all_cards = [row["scryfall_id"] for row in conn.execute("SELECT scryfall_id FROM cards").fetchall()]
    market_sets = tuple(sorted(market_eligible_set_codes()))
    placeholders = ",".join("?" for _ in market_sets)
    market_pool = [
        row["scryfall_id"]
        for row in conn.execute(
            f"""
            SELECT scryfall_id FROM cards
            WHERE upper(set_code) IN ({placeholders})
            LIMIT 5000
            """,
            market_sets,
        ).fetchall()
    ]
    not_owned = [card_id for card_id in all_cards if card_id not in set(owned)]

    picks: list[dict[str, Any]] = []
    for card_id in rng.sample(owned, min(3, len(owned))):
        finish = conn.execute(
            "SELECT finish FROM collection_items WHERE scryfall_id = ? AND quantity > 0 LIMIT 1",
            (card_id,),
        ).fetchone()
        picks.append({"scryfall_id": card_id, "finish": finish["finish"] if finish else "nonfoil", "bucket": "collection"})
    for card_id in rng.sample(not_owned, min(3, len(not_owned))):
        picks.append({"scryfall_id": card_id, "finish": "nonfoil", "bucket": "hors_collection"})
    for card_id in rng.sample(market_pool, min(2, len(market_pool))):
        picks.append({"scryfall_id": card_id, "finish": "nonfoil", "bucket": "market"})
    remaining = [c for c in all_cards if c not in {p["scryfall_id"] for p in picks}]
    for card_id in rng.sample(remaining, min(2, len(remaining))):
        picks.append({"scryfall_id": card_id, "finish": "foil", "bucket": "random"})
    return picks[:10]


def benchmark_card(conn, sample: dict[str, Any]) -> dict[str, Any]:
    scryfall_id = sample["scryfall_id"]
    finish = sample.get("finish") or "nonfoil"
    result: dict[str, Any] = {**sample, "checks": {}, "timings_ms": {}, "errors": []}

    t0 = time.perf_counter()
    try:
        card = get_cached_card(conn, scryfall_id)
        result["timings_ms"]["get_cached_card"] = _ms(t0)
        result["checks"]["card_found"] = card is not None
        if not card:
            result["errors"].append("card_not_found")
            return result
        result["name"] = card.get("name")
        result["set_code"] = card.get("set") or card.get("set_code")
    except Exception as error:  # noqa: BLE001
        result["errors"].append(f"get_cached_card: {error}")
        return result

    t0 = time.perf_counter()
    try:
        price = display_price_for(conn, card, finish)
        result["timings_ms"]["display_price"] = _ms(t0)
        result["checks"]["display_price"] = float(price.price) if price else None
        result["checks"]["display_price_source"] = price.source if price else None
    except Exception as error:  # noqa: BLE001
        result["errors"].append(f"display_price: {error}")

    t0 = time.perf_counter()
    try:
        guide = cardmarket_latest_guide_for_card(conn, scryfall_id, finish)
        result["timings_ms"]["cm_latest_guide"] = _ms(t0)
        result["checks"]["cm_trend"] = (guide or {}).get("metrics", {}).get("trend")
        result["checks"]["cm_low"] = (guide or {}).get("metrics", {}).get("low")
    except Exception as error:  # noqa: BLE001
        result["errors"].append(f"cm_guide: {error}")

    t0 = time.perf_counter()
    try:
        history = price_history(conn, scryfall_id, finish)
        result["timings_ms"]["price_history"] = _ms(t0)
        result["checks"]["history_points"] = len(history)
        result["checks"]["history_sources"] = sorted({p.get("source") for p in history})
        if history:
            result["checks"]["history_last"] = {
                "date": history[-1].get("snapshot_date"),
                "price": history[-1].get("price"),
                "source": history[-1].get("source"),
            }
    except Exception as error:  # noqa: BLE001
        result["errors"].append(f"price_history: {error}")

    for alt_finish in ("nonfoil", "foil", "etched"):
        if alt_finish == finish:
            continue
        t0 = time.perf_counter()
        try:
            h = price_history(conn, scryfall_id, alt_finish)
            result["timings_ms"][f"history_{alt_finish}"] = _ms(t0)
            result["checks"][f"history_{alt_finish}_points"] = len(h)
        except Exception as error:  # noqa: BLE001
            result["errors"].append(f"history_{alt_finish}: {error}")

    return result


def benchmark_heavy(conn) -> dict[str, Any]:
    heavy: dict[str, Any] = {"timings_ms": {}, "errors": []}

  # collection summary-ish
    t0 = time.perf_counter()
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT scryfall_id) u, SUM(quantity) q
            FROM collection_items WHERE quantity > 0
            """
        ).fetchone()
        heavy["timings_ms"]["collection_aggregate"] = _ms(t0)
        heavy["collection_unique"] = row["u"]
        heavy["collection_qty"] = row["q"]
    except Exception as error:  # noqa: BLE001
        heavy["errors"].append(str(error))

    t0 = time.perf_counter()
    try:
        from mtg_pwa.server import HistoryBuildOptions, market_price_movers

        payload = market_price_movers(
            conn,
            "cardmarket",
            HistoryBuildOptions(market_scope="all", exclude_illiquid=True),
            range_key="7d",
        )
        heavy["timings_ms"]["market_movers_cm_7d"] = _ms(t0)
        heavy["market_tracked"] = payload.get("tracked_cards")
        heavy["market_mover_sample"] = len(payload.get("top_pct_gain") or [])
    except Exception as error:  # noqa: BLE001
        heavy["errors"].append(f"market_movers: {error}")

    t0 = time.perf_counter()
    try:
        from mtg_pwa.server import HistoryBuildOptions, collection_valuation_history

        collection_valuation_history(
            conn,
            "cardmarket",
            HistoryBuildOptions(history_mode="fast"),
            range_key="1m",
        )
        heavy["timings_ms"]["collection_history_fast_1m"] = _ms(t0)
    except Exception as error:  # noqa: BLE001
        heavy["errors"].append(f"collection_history: {error}")

    t0 = time.perf_counter()
    try:
        from mtg_pwa.database import catalog_object_type
        from mtg_pwa.price_daily import count_narrow_price_cells

        if catalog_object_type(conn, "price_snapshots") == "view":
            n = count_narrow_price_cells(conn)
        else:
            n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        heavy["timings_ms"]["count_price_snapshots"] = _ms(t0)
        heavy["price_snapshots_rows"] = int(n)
    except Exception as error:  # noqa: BLE001
        heavy["errors"].append(f"count_snapshots: {error}")

    return heavy


def run_validation(*, db_path: Path | str | None = None, label: str | None = None) -> dict[str, Any]:
    path = Path(db_path or DEFAULT_DB_PATH)
    conn = connect(path)
    init_db(conn)
    try:
        samples = pick_samples(conn)
        cards = [benchmark_card(conn, sample) for sample in samples]
        heavy = benchmark_heavy(conn)
        db_size_gb = round(path.stat().st_size / (1024**3), 3) if path.exists() else None
        payload = {
            "label": label or date.today().isoformat(),
            "db_path": str(path),
            "db_size_gb": db_size_gb,
            "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "samples": cards,
            "heavy": heavy,
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"validation_{payload['label']}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        payload["output_file"] = str(out)
        return payload
    finally:
        conn.close()


def compare(before_path: Path, after_path: Path) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    by_id_before = {s["scryfall_id"]: s for s in before.get("samples", [])}
    by_id_after = {s["scryfall_id"]: s for s in after.get("samples", [])}

    card_diffs: list[dict[str, Any]] = []
    for card_id, b in by_id_before.items():
        a = by_id_after.get(card_id)
        if not a:
            card_diffs.append({"scryfall_id": card_id, "error": "missing_after"})
            continue
        checks_b = b.get("checks") or {}
        checks_a = a.get("checks") or {}
        price_b = checks_b.get("display_price")
        price_a = checks_a.get("display_price")
        trend_b = checks_b.get("cm_trend")
        trend_a = checks_a.get("cm_trend")
        card_diffs.append(
            {
                "scryfall_id": card_id,
                "bucket": b.get("bucket"),
                "display_price_delta": None if price_b is None or price_a is None else round(price_a - price_b, 4),
                "cm_trend_delta": None if trend_b is None or trend_a is None else round(trend_a - trend_b, 4),
                "history_points_before": checks_b.get("history_points"),
                "history_points_after": checks_a.get("history_points"),
                "errors_before": b.get("errors"),
                "errors_after": a.get("errors"),
                "timings_before_ms": b.get("timings_ms"),
                "timings_after_ms": a.get("timings_ms"),
            }
        )

    heavy_b = before.get("heavy", {}).get("timings_ms", {})
    heavy_a = after.get("heavy", {}).get("timings_ms", {})
    heavy_compare = {
        key: {
            "before_ms": heavy_b.get(key),
            "after_ms": heavy_a.get(key),
            "delta_ms": None
            if heavy_b.get(key) is None or heavy_a.get(key) is None
            else round(heavy_a[key] - heavy_b[key], 1),
        }
        for key in sorted(set(heavy_b) | set(heavy_a))
    }

    ok = all(not d.get("errors_after") for d in card_diffs)
  # price tolerance: display within 0.01, cm trend within 0.01
    for d in card_diffs:
        if d.get("display_price_delta") is not None and abs(d["display_price_delta"]) > 0.02:
            d["price_regression"] = True
            ok = False
        if d.get("cm_trend_delta") is not None and abs(d["cm_trend_delta"]) > 0.02:
            d["trend_regression"] = True
            ok = False

    report = {
        "ok": ok,
        "db_size_gb_before": before.get("db_size_gb"),
        "db_size_gb_after": after.get("db_size_gb"),
        "cards": card_diffs,
        "heavy": heavy_compare,
    }
    out = RESULTS_DIR / f"comparison_{before_path.stem}_vs_{after_path.stem}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["output_file"] = str(out)
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if args.compare:
        report = compare(Path(args.compare[0]), Path(args.compare[1]))
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    payload = run_validation(db_path=args.db, label=args.label or "baseline")
    print(json.dumps({"output_file": payload["output_file"], "heavy": payload["heavy"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
