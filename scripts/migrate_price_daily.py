#!/usr/bin/env python3
"""Migration price_snapshots -> price_daily + vue de compatibilite."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH, connect, init_db  # noqa: E402
from mtg_pwa.price_daily import (  # noqa: E402
    drop_legacy_snapshot_indexes,
    install_price_snapshots_view,
    migrate_snapshots_to_daily,
    verify_migration,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-vacuum", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = connect(db_path)
    init_db(conn)

    if args.dry_run:
        stats = conn.execute(
            """
            SELECT COUNT(*) AS rows,
                   COUNT(DISTINCT snapshot_date) AS days,
                   COUNT(DISTINCT scryfall_id) AS cards
            FROM price_snapshots
            WHERE source NOT IN ('mtgjson-cardmarket')
              AND source NOT LIKE 'scryfall-cardmarket-en-print:%'
            """
        ).fetchone()
        est_daily = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT snapshot_date, scryfall_id
              FROM price_snapshots
              WHERE source NOT IN ('mtgjson-cardmarket')
                AND source NOT LIKE 'scryfall-cardmarket-en-print:%'
              GROUP BY snapshot_date, scryfall_id
            )
            """
        ).fetchone()[0]
        payload = {
            "dry_run": True,
            "narrow_rows": int(stats["rows"]),
            "distinct_days": int(stats["days"]),
            "distinct_cards": int(stats["cards"]),
            "estimated_daily_rows": int(est_daily),
        }
        print(json.dumps(payload, indent=2))
        conn.close()
        return 0

    started = time.time()

    def on_progress(index: int, total: int, snapshot_date: str, rows: int) -> None:
        print(f"[{index}/{total}] {snapshot_date} -> {rows} lignes daily cumul", flush=True)

    migrate_stats = migrate_snapshots_to_daily(conn, on_progress=on_progress)
    install_price_snapshots_view(conn)
    drop_legacy_snapshot_indexes(conn)
    check = verify_migration(conn)
    if not check.get("match"):
        print("ERREUR verification:", json.dumps(check, indent=2), file=sys.stderr)
        conn.close()
        return 1

    if not args.skip_vacuum:
        print("VACUUM en cours (peut prendre plusieurs minutes)...", flush=True)
        conn.execute("VACUUM")
        conn.commit()

    elapsed = round(time.time() - started, 1)
    size_gb = round(db_path.stat().st_size / (1024**3), 3)
    result = {
        "ok": True,
        "elapsed_s": elapsed,
        "db_size_gb": size_gb,
        "migrate": migrate_stats,
        "verify": check,
    }
    print(json.dumps(result, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
