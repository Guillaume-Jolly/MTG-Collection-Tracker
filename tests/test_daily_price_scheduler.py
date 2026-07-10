from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import launcher.daily_price_scheduler as scheduler


class DailyPriceSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "state.json"
        self.state_patch = patch.object(scheduler, "STATE_PATH", self.state_path)
        self.state_patch.start()

    def tearDown(self) -> None:
        self.state_patch.stop()
        self.temp_dir.cleanup()

    def test_should_show_prompt_false_when_archive_done(self) -> None:
        self.state_path.write_text(json.dumps({"snooze_until": "2099-01-01T00:00:00+00:00"}), encoding="utf-8")
        with patch.object(scheduler, "archive_completed_today", return_value=True):
            self.assertFalse(scheduler.should_show_prompt())
            self.assertNotIn("snooze_until", json.loads(self.state_path.read_text(encoding="utf-8")))

    def test_should_show_prompt_false_when_snoozed(self) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=30)
        self.state_path.write_text(
            json.dumps({"snooze_until": until.isoformat()}),
            encoding="utf-8",
        )
        with patch.object(scheduler, "archive_completed_today", return_value=False):
            self.assertFalse(scheduler.should_show_prompt())

    def test_snooze_for_one_hour(self) -> None:
        with patch.object(scheduler, "archive_completed_today", return_value=False):
            scheduler.snooze_for_one_hour()
            self.assertTrue(scheduler.is_snoozed())
            self.assertFalse(scheduler.should_show_prompt())

    def test_estimate_progress_for_writing_phase(self) -> None:
        percent = scheduler.estimate_progress_percent(
            {"phase": "writing", "cards_processed": 500, "cards_total": 1000}
        )
        self.assertGreater(percent, 45.0)
        self.assertLess(percent, 80.0)

    def test_manual_flow_skips_when_user_declines_force(self) -> None:
        with patch.object(scheduler, "archive_completed_today", return_value=True):
            root = scheduler.tk.Tk()
            root.withdraw()
            with patch.object(
                scheduler.messagebox,
                "askyesno",
                return_value=False,
            ) as ask_mock:
                self.assertEqual(scheduler.run_manual_flow(), 0)
            ask_mock.assert_called_once()
            root.destroy()

    def test_archive_progress_on_status_accepts_status_dict(self) -> None:
        captured: list[dict] = []

        def on_status(updates: dict) -> None:
            captured.append(updates)

        on_status({"phase": "writing", "cards_processed": 1, "cards_total": 10})
        self.assertEqual(captured[0]["phase"], "writing")
        self.assertEqual(captured[0]["cards_processed"], 1)

    def test_archive_completed_today_reads_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            from mtg_pwa.database import connect, init_db, set_app_metadata

            conn = connect(db_path)
            init_db(conn)
            set_app_metadata(conn, scheduler.LAST_CARDMARKET_ARCHIVE_DATE_KEY, date.today().isoformat())
            conn.commit()
            conn.close()
            self.assertTrue(scheduler.archive_completed_today(db_path=db_path))


if __name__ == "__main__":
    unittest.main()
