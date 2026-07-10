#!/usr/bin/env python3
"""Termine une migration price_daily interrompue (indexes + verify + VACUUM)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH, connect  # noqa: E402
from mtg_pwa.price_daily import drop_legacy_snapshot_indexes, verify_migration  # noqa: E402


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--skip-vacuum", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = connect(db_path)
    started = time.time()

    drop_legacy_snapshot_indexes(conn)
    check = verify_migration(conn)
    if not check.get("match"):
        print("ERREUR verification:", json.dumps(check, indent=2), file=sys.stderr)
        conn.close()
        return 1

    if not args.skip_vacuum:
        print("VACUUM en cours...", flush=True)
        conn.execute("VACUUM")
        conn.commit()

    elapsed = round(time.time() - started, 1)
    size_gb = round(db_path.stat().st_size / (1024**3), 3)
    print(json.dumps({"ok": True, "elapsed_s": elapsed, "db_size_gb": size_gb, "verify": check}, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
