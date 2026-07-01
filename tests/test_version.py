from __future__ import annotations

import json
import unittest
from pathlib import Path

from mtg_pwa.version import app_version_label, format_session_label, package_semver


class AppVersionTest(unittest.TestCase):
    def test_package_semver(self) -> None:
        self.assertEqual(package_semver(), "1.1.0")

    def test_format_session_label_without_y(self) -> None:
        self.assertEqual(format_session_label("1.1.0", 5, 0), "v1.1.0.05")

    def test_format_session_label_with_y(self) -> None:
        self.assertEqual(format_session_label("1.1.0", 5, 3), "v1.1.0.05.3")

    def test_app_version_label_reads_build_revision(self) -> None:
        root = Path(__file__).resolve().parents[1]
        revision_path = root / "build-revision.json"
        if not revision_path.exists():
            self.skipTest("build-revision.json absent")
        data = json.loads(revision_path.read_text(encoding="utf-8"))
        revision = int(data.get("revision", 1))
        sub = int(data.get("subRevision", 0))
        expected = format_session_label(package_semver(), revision, sub)
        self.assertEqual(app_version_label(), expected)


if __name__ == "__main__":
    unittest.main()
