#!/usr/bin/env python3
"""Copie de securite fichier SQLite vers E:\\Backup\\MTG Data\\temp."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mtg_pwa.database import DEFAULT_DB_PATH  # noqa: E402

DEFAULT_TEMP_ROOT = Path(r"E:\Backup\MTG Data\temp")


def file_sha256(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_sqlite(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        object_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='price_snapshots'"
        ).fetchone()
        if object_type and object_type[0] == "view":
            sys.path.insert(0, str(REPO_ROOT))
            from mtg_pwa.price_daily import count_narrow_price_cells

            ps_count = count_narrow_price_cells(conn)
        else:
            ps_count = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        coll_count = conn.execute("SELECT COUNT(*) FROM collection_items WHERE quantity > 0").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "integrity": integrity,
            "page_count": page_count,
            "page_size": page_size,
            "size_gb": round(path.stat().st_size / (1024**3), 3),
            "price_snapshots": int(ps_count),
            "collection_items": int(coll_count),
        }
    finally:
        conn.close()


def run_safety_backup(
    *,
    source: Path | None = None,
    dest_dir: Path | None = None,
    label: str | None = None,
) -> dict:
    src = Path(source or DEFAULT_DB_PATH).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Base source introuvable: {src}")

    tag = label or date.today().isoformat()
    folder = Path(dest_dir or (DEFAULT_TEMP_ROOT / f"pre_opt_{tag}"))
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "mtg_pwa.sqlite3"

    started = time.time()
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy2(side, folder / ("mtg_pwa.sqlite3" + suffix))

    elapsed = round(time.time() - started, 1)
    src_hash = file_sha256(src)
    dest_hash = file_sha256(dest)
    meta = {
        "label": tag,
        "source": str(src),
        "dest_dir": str(folder),
        "dest_db": str(dest),
        "elapsed_s": elapsed,
        "sha256_match": src_hash == dest_hash,
        "sha256": dest_hash,
        "source_stats": validate_sqlite(src),
        "dest_stats": validate_sqlite(dest),
        "ok": src_hash == dest_hash and validate_sqlite(dest)["integrity"] == "ok",
    }
    (folder / "backup_manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=None)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()
    dest = Path(args.dest) if args.dest else None
    meta = run_safety_backup(dest_dir=dest, label=args.label)
    print(json.dumps(meta, indent=2))
    return 0 if meta["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
