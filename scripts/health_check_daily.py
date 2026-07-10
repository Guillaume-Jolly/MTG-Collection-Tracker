#!/usr/bin/env python3
"""Santé post-mise à jour journalière."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH, connect, init_db, price_history  # noqa: E402
from mtg_pwa.price_daily import count_narrow_price_cells, verify_migration  # noqa: E402


def main() -> int:
    db = Path(DEFAULT_DB_PATH)
    conn = connect(db)
    init_db(conn)

    report: dict = {"date": date.today().isoformat(), "db_size_gb": round(db.stat().st_size / (1024**3), 3)}

    report["price_daily"] = dict(
        conn.execute(
            "SELECT COUNT(*) AS rows, MIN(snapshot_date) AS min_date, MAX(snapshot_date) AS max_date FROM price_daily"
        ).fetchone()
    )
    report["cm_guide"] = dict(
        conn.execute(
            """
            SELECT COUNT(DISTINCT snapshot_date) AS days,
                   MIN(snapshot_date) AS min_date,
                   MAX(snapshot_date) AS max_date,
                   COUNT(*) AS rows
            FROM cardmarket_price_guide_daily
            """
        ).fetchone()
    )
    report["collection"] = dict(
        conn.execute(
            "SELECT COUNT(DISTINCT scryfall_id) AS unique_cards, SUM(quantity) AS qty FROM collection_items WHERE quantity > 0"
        ).fetchone()
    )

    today = date.today().isoformat()
    report["today"] = {
        "date": today,
        "price_daily_rows": conn.execute(
            "SELECT COUNT(*) FROM price_daily WHERE snapshot_date = ?", (today,)
        ).fetchone()[0],
        "guide_rows": conn.execute(
            "SELECT COUNT(*) FROM cardmarket_price_guide_daily WHERE snapshot_date = ?", (today,)
        ).fetchone()[0],
    }

    meta_rows = conn.execute(
        """
        SELECT key, value, updated_at FROM app_metadata
        ORDER BY updated_at DESC LIMIT 20
        """
    ).fetchall()
    report["recent_metadata"] = [dict(r) for r in meta_rows]

    legacy_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone()
    if legacy_exists:
        report["verify_migration"] = verify_migration(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        report["integrity_check"] = integrity

    t0 = time.perf_counter()
    report["count_price_cells_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    report["price_cells"] = count_narrow_price_cells(conn)

    # quick functional checks
    sample = conn.execute(
        "SELECT scryfall_id, finish FROM collection_items WHERE quantity > 0 ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if sample:
        t0 = time.perf_counter()
        hist = price_history(conn, sample["scryfall_id"], sample["finish"])
        report["sample_card"] = {
            "scryfall_id": sample["scryfall_id"],
            "finish": sample["finish"],
            "history_points": len(hist),
            "history_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    t0 = time.perf_counter()
    try:
        from mtg_pwa.server import HistoryBuildOptions, market_price_movers

        movers = market_price_movers(
            conn,
            "cardmarket",
            HistoryBuildOptions(market_scope="all", exclude_illiquid=True),
            range_key="7d",
        )
        report["market_movers_7d"] = {
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "tracked": movers.get("tracked_cards"),
            "start_date": movers.get("start_date"),
            "end_date": movers.get("end_date"),
            "top_pct_gain": len(movers.get("top_pct_gain") or []),
        }
    except Exception as exc:  # noqa: BLE001
        report["market_movers_7d"] = {"error": str(exc)}

    today_collected = conn.execute(
        "SELECT COUNT(*) FROM price_daily WHERE collected_at LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]
    report["today"]["price_daily_collected_today"] = int(today_collected)

    issues = []
    if report.get("integrity_check") not in (None, "ok"):
        issues.append(f"integrity_check: {report['integrity_check']}")
    verify = report.get("verify_migration") or {}
    if verify and not verify.get("match"):
        legacy_active = int(verify.get("legacy_active_rows") or 0)
        daily_cells = int(verify.get("daily_price_cells") or 0)
        view_rows = int(verify.get("view_narrow_rows") or 0)
        if daily_cells < legacy_active:
            issues.append("verify_migration: daily < legacy active (regression)")
        elif daily_cells != view_rows:
            issues.append(
                "verify_migration: price_daily vs view mismatch "
                f"(daily={daily_cells}, view={view_rows})"
            )
    if report["today"]["guide_rows"] == 0:
        issues.append(f"aucune ligne guide CM pour {today}")
    if report["cm_guide"]["max_date"] != today:
        issues.append(f"guide CM pas à jour (max={report['cm_guide']['max_date']})")
    archive_date = next(
        (m["value"] for m in report["recent_metadata"] if m["key"] == "last_price_archive_date"),
        None,
    )
    if archive_date != today and today_collected == 0:
        issues.append(f"archivage MTGJSON pas à jour (last={archive_date})")

    report["ok"] = len(issues) == 0
    report["issues"] = issues

    out = REPO_ROOT / "data" / "validation_runs" / f"health_{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    conn.close()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
