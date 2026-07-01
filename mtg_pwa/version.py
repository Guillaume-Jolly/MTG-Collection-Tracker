"""Application version label — semver (package.json) + session X/Y (build-revision.json)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Fallback semver when package.json is missing (keep aligned on release kickoff).
APP_VERSION_MAJOR = 1
APP_VERSION_MINOR = 1
APP_VERSION_PATCH = 0


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def package_semver() -> str:
    pkg = _read_json(_REPO_ROOT / "package.json")
    if pkg and pkg.get("version"):
        return str(pkg["version"])
    return f"{APP_VERSION_MAJOR}.{APP_VERSION_MINOR}.{APP_VERSION_PATCH}"


def format_session_label(semver: str, revision: int, sub_revision: int) -> str:
    x = f"{int(revision):02d}"
    base = f"v{semver}.{x}"
    if sub_revision > 0:
        return f"{base}.{int(sub_revision)}"
    return base


def app_version_label() -> str:
    build_info = _read_json(_REPO_ROOT / "public" / "build-info.json")
    if build_info:
        for key in ("versionLabel", "label"):
            if build_info.get(key):
                return str(build_info[key])
    revision_data = _read_json(_REPO_ROOT / "build-revision.json") or {
        "revision": 1,
        "subRevision": 0,
    }
    semver = package_semver()
    return format_session_label(
        semver,
        int(revision_data.get("revision", 1)),
        int(revision_data.get("subRevision", 0)),
    )


def version_identity() -> dict[str, str]:
    """Project flags for health API and UI."""
    build_info = _read_json(_REPO_ROOT / "public" / "build-info.json")
    if build_info and build_info.get("projectLabel"):
        return {
            "projectName": str(build_info["projectLabel"]),
            "projectSlug": str(build_info.get("projectSlug") or "mtg-tracker"),
            "versionPackId": str(build_info.get("versionPackId") or "cursor-abc-xy-reference-v1"),
        }
    revision_data = _read_json(_REPO_ROOT / "build-revision.json")
    if revision_data and revision_data.get("projectSlug"):
        return {
            "projectName": str(revision_data.get("projectName") or "MTG Tracker"),
            "projectSlug": str(revision_data["projectSlug"]),
            "versionPackId": str(revision_data.get("versionPackId") or "cursor-abc-xy-reference-v1"),
        }
    pkg = _read_json(_REPO_ROOT / "package.json")
    return {
        "projectName": "MTG Tracker",
        "projectSlug": str(pkg.get("name") if pkg else "mtg-tracker"),
        "versionPackId": "cursor-abc-xy-reference-v1",
    }


def sync_build_info() -> None:
    """Refresh public/build-info.json git metadata without bumping X or Y."""
    script = _REPO_ROOT / "scripts" / "sync-build-info.mjs"
    if not script.exists():
        return
    try:
        subprocess.run(
            ["node", str(script)],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return
