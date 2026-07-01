from __future__ import annotations

import json
import unittest
from pathlib import Path

from mtg_pwa.version import app_version_label, format_session_label, package_semver


class AppVersionTest(unittest.TestCase):
    def test_package_semver(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package_semver(), str(pkg["version"]))

    def test_format_session_label_without_y(self) -> None:
        semver = package_semver()
        self.assertEqual(format_session_label(semver, 5, 0), f"v{semver}.05")

    def test_format_session_label_with_y(self) -> None:
        semver = package_semver()
        self.assertEqual(format_session_label(semver, 5, 3), f"v{semver}.05.3")

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
