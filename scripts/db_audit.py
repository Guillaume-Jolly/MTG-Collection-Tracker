#!/usr/bin/env python3
"""Audit volumetrie BDD + backup — CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.db_audit import collect_db_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit taille BDD MTG Tracker")
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    parser.add_argument("--backup-root", default=None, help="Racine backup (defaut E:\\Backup\\MTG Data)")
    args = parser.parse_args()
    audit = collect_db_audit(backup_root=args.backup_root)

    if args.json:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
        return 0

    main_db = audit["db_files"].get("main", {})
    print(f"=== Audit BDD MTG Tracker ({audit['audit_date']}) ===")
    print(f"Statut global : {audit['overall_status'].upper()}")
    print(f"Base principale : {main_db.get('path')}")
    print(f"  Taille fichier : {main_db.get('size_gb', 0):.2f} Go")
    if audit.get("growth_projection_month_gb"):
        print(f"  Croissance estimee : ~{audit['growth_projection_month_gb']:.1f} Go/mois")
    print(f"price_snapshots : {audit['price_snapshots'].get('total_rows', 0):,} lignes")
    print("\n--- Tables (lignes) ---")
    for name, count in sorted((audit.get("tables") or {}).items()):
        if count is not None:
            print(f"  {name}: {count:,}")
    print("\n--- Backup ---")
    backup = audit.get("backup") or {}
    print(f"  {backup.get('db_path')} : {backup.get('size_gb', 0) or 0:.2f} Go ({'present' if backup.get('exists') else 'absent'})")
    for label, disk in (audit.get("disks") or {}).items():
        print(f"  Disque {label}: {disk.get('free_gb')} Go libres / {disk.get('total_gb')} Go")
    if audit.get("warnings"):
        print("\n--- Alertes ---")
        for w in audit["warnings"]:
            print(f"  [{w['level']}] {w['message']}")
    tech = audit.get("tech_stack") or {}
    print("\n--- Techno ---")
    print(f"  {tech.get('verdict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
