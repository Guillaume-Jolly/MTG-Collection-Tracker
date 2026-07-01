from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mtg_pwa.startup_warmup import warmup_recently_done


class StartupWarmupTest(unittest.TestCase):
    def test_warmup_recently_done_true(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        class FakeConn:
            pass

        with patch("mtg_pwa.startup_warmup.get_app_metadata", return_value=recent):
            self.assertTrue(warmup_recently_done(FakeConn()))

    def test_warmup_recently_done_false_when_missing(self) -> None:
        class FakeConn:
            pass

        with patch("mtg_pwa.startup_warmup.get_app_metadata", return_value=None):
            self.assertFalse(warmup_recently_done(FakeConn()))


if __name__ == "__main__":
    unittest.main()
