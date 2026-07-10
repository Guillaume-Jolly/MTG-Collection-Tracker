from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from mtg_pwa.database import connect, init_db, set_app_metadata
from mtg_pwa.db_audit import _warning_level, collect_db_audit, tech_stack_audit
from mtg_pwa.weekly_backup import (
    LAST_WEEKLY_BACKUP_DATE_KEY,
    run_weekly_backup,
    weekly_backup_already_done_this_week,
)


class DbAuditTests(unittest.TestCase):
    def test_warning_level_thresholds(self) -> None:
        self.assertEqual(_warning_level(5, info=6, warning=8, critical=12), "ok")
        self.assertEqual(_warning_level(9, info=6, warning=8, critical=12), "warning")
        self.assertEqual(_warning_level(13, info=6, warning=8, critical=12), "critical")

    def test_tech_stack_recommends_multi_db_at_scale(self) -> None:
        tech = tech_stack_audit(main_db_gb=10, price_snapshots_rows=20_000_000)
        self.assertTrue(tech["multi_db_recommended"])
        self.assertIn("SQLite", tech["current_stack"])

    def test_collect_db_audit_on_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            conn = connect(db_path)
            init_db(conn)
            conn.execute(
                """
                INSERT INTO cards (scryfall_id, name, raw_json, updated_at)
                VALUES ('x', 'Test', '{}', '2026-07-09')
                """
            )
            conn.commit()
            conn.close()
            (Path(tmp) / "backup").mkdir(parents=True, exist_ok=True)
            audit = collect_db_audit(db_path=db_path, backup_root=Path(tmp) / "backup")
            self.assertIn("tables", audit)
            self.assertIn(audit["overall_status"], {"ok", "info"})
            self.assertGreaterEqual(audit["db_files"]["main"]["size_gb"], 0)


class WeeklyBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.sqlite3"
        self.backup_root = self.root / "backup"
        conn = connect(self.source)
        init_db(conn)
        conn.execute(
            """
            INSERT INTO cards (scryfall_id, name, raw_json, updated_at)
            VALUES ('abc', 'Bolt', '{}', '2026-07-09')
            """
        )
        conn.execute(
            """
            INSERT INTO collection_items (
                scryfall_id, quantity, finish, condition, created_at, updated_at
            ) VALUES ('abc', 2, 'nonfoil', 'near_mint', 't', 't')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_weekly_backup_skips_within_week(self) -> None:
        conn = connect(self.source)
        init_db(conn)
        set_app_metadata(conn, LAST_WEEKLY_BACKUP_DATE_KEY, date.today().isoformat())
        conn.commit()
        self.assertTrue(weekly_backup_already_done_this_week(conn, force=False))
        conn.close()

    def test_weekly_backup_inserts_collection_history(self) -> None:
        result = run_weekly_backup(db_path=self.source, backup_root=self.backup_root, force=True)
        self.assertFalse(result.get("skipped"))
        self.assertGreater(result.get("rows_snapshot", 0), 0)
        backup_path = self.backup_root / "mtg_cumulative.sqlite3"
        self.assertTrue(backup_path.exists())
        backup = connect(backup_path)
        count = backup.execute("SELECT COUNT(*) FROM collection_items_history").fetchone()[0]
        backup.close()
        self.assertEqual(int(count), 1)

    def test_second_run_skips_same_week(self) -> None:
        run_weekly_backup(db_path=self.source, backup_root=self.backup_root, force=True)
        result = run_weekly_backup(db_path=self.source, backup_root=self.backup_root, force=False)
        self.assertTrue(result.get("skipped"))


if __name__ == "__main__":
    unittest.main()
