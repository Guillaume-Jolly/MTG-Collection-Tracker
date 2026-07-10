#!/usr/bin/env python3
"""Reconstruit price_daily depuis price_snapshots_legacy (apres fix colonnes)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH, connect  # noqa: E402
from mtg_pwa.price_daily import (  # noqa: E402
    migrate_snapshots_to_daily,
    price_daily_table,
    verify_migration,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--skip-vacuum", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = connect(db_path)
    legacy = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone()
    if not legacy:
        print("price_snapshots_legacy manquant", file=sys.stderr)
        conn.close()
        return 1

    started = time.time()
    conn.execute(f"DELETE FROM {price_daily_table()}")
    conn.commit()
    print("price_daily vide, migration...", flush=True)

    def on_progress(index: int, total: int, snapshot_date: str, rows: int) -> None:
        if index % 10 == 0 or index == total:
            print(f"[{index}/{total}] {snapshot_date} -> {rows} lignes/jour", flush=True)

    stats = migrate_snapshots_to_daily(conn, on_progress=on_progress)
    check = verify_migration(conn)
    if not check.get("match"):
        print("ERREUR verification:", json.dumps(check, indent=2), file=sys.stderr)
        conn.close()
        return 1

    if not args.skip_vacuum:
        print("VACUUM...", flush=True)
        conn.execute("VACUUM")
        conn.commit()

    elapsed = round(time.time() - started, 1)
    size_gb = round(db_path.stat().st_size / (1024**3), 3)
    print(json.dumps({"ok": True, "elapsed_s": elapsed, "db_size_gb": size_gb, "migrate": stats, "verify": check}, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
