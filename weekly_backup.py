#!/usr/bin/env python3
"""Backup hebdomadaire cumulatif vers E:\\Backup\\MTG Data (insert only)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.weekly_backup import run_weekly_backup, weekly_backup_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup hebdomadaire MTG Tracker")
    parser.add_argument("--force", action="store_true", help="Ignorer la fenetre 7 jours")
    parser.add_argument("--status", action="store_true", help="Statut seulement")
    parser.add_argument("--backup-root", default=None, help="Racine backup")
    args = parser.parse_args()

    if args.status:
        import json

        print(json.dumps(weekly_backup_status(backup_root=args.backup_root), indent=2, ensure_ascii=False))
        return 0

    try:
        result = run_weekly_backup(force=args.force, backup_root=args.backup_root)
    except Exception as error:  # noqa: BLE001
        print(f"Erreur backup: {error}", file=sys.stderr)
        return 1

    if result.get("skipped"):
        print(f"Skip: deja fait ({result.get('backup_date')})")
        return 0
    if result.get("error") and not result.get("finished_at"):
        print(f"Erreur: {result['error']}", file=sys.stderr)
        return 1
    print(
        f"OK run={result.get('run_id')} +{result.get('rows_incremental')} inc, "
        f"{result.get('rows_snapshot')} snap, {result.get('backup_size_gb')} Go"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
