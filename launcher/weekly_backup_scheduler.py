"""Planificateur backup hebdomadaire — une fois par semaine max.

Usage:
  python launcher/weekly_backup_scheduler.py
  python launcher/weekly_backup_scheduler.py --check-only
  python launcher/weekly_backup_scheduler.py --force-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.db_audit import collect_db_audit  # noqa: E402
from mtg_pwa.weekly_backup import run_weekly_backup, weekly_backup_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--force-run", action="store_true")
    args = parser.parse_args()

    status = weekly_backup_status()
    audit = collect_db_audit()

    print(f"Backup due: {status['due']} (dernier: {status.get('last_backup_date') or 'jamais'})")
    print(f"DB: {audit['db_files']['main'].get('size_gb')} Go — statut {audit['overall_status']}")
    for warning in audit.get("warnings") or []:
        print(f"  [{warning['level']}] {warning['message']}")

    if args.check_only:
        return 0

    if not args.force_run and not status["due"]:
        print("Backup hebdo deja a jour (< 7 jours).")
        return 0

    result = run_weekly_backup(force=args.force_run)
    if result.get("skipped"):
        print("Skip.")
        return 0
    if result.get("error"):
        print(f"Erreur: {result['error']}", file=sys.stderr)
        return 1
    print(f"Backup OK: {result.get('backup_size_gb')} Go")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
