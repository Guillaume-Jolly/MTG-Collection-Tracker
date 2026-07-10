from __future__ import annotations

import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB_PATH, catalog_table, connect, init_db, shared_prices_db_path, uses_shared_catalog

# Seuils par défaut — base opérationnelle (data/mtg_pwa.sqlite3)
MAIN_DB_INFO_GB = 6.0
MAIN_DB_WARNING_GB = 8.0
MAIN_DB_CRITICAL_GB = 12.0

# Disque E: (backup) — alerte si espace libre < seuil (300 Go dispos chez vous, marge confortable)
BACKUP_DISK_WARNING_FREE_GB = 80.0
BACKUP_DISK_CRITICAL_FREE_GB = 30.0
BACKUP_DB_WARNING_GB = 15.0
BACKUP_DB_CRITICAL_GB = 40.0

DEFAULT_BACKUP_ROOT = Path(r"E:\Backup\MTG Data")
BACKUP_DB_NAME = "mtg_cumulative.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def disk_usage(path: Path) -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        "path": str(path),
        "total_gb": round(usage.total / (1024**3), 2),
        "used_gb": round(usage.used / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "used_pct": round((usage.used / usage.total) * 100, 1) if usage.total else None,
    }


def _warning_level(value_gb: float, *, info: float, warning: float, critical: float) -> str:
    if value_gb >= critical:
        return "critical"
    if value_gb >= warning:
        return "warning"
    if value_gb >= info:
        return "info"
    return "ok"


def _table_row_count(conn, table: str) -> int | None:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None


def _price_snapshot_date_stats(conn) -> dict[str, Any]:
    try:
        from .database import catalog_object_type, get_app_metadata
        from .price_daily import count_narrow_price_cells, daily_stats_by_date

        if catalog_object_type(conn, "price_snapshots") == "view":
            cached_total = get_app_metadata(conn, "price_daily_cell_count")
            total = int(cached_total) if cached_total else count_narrow_price_cells(conn)
            dates = [
                {"date": row["date"], "rows": row["cells"]}
                for row in daily_stats_by_date(conn, limit=10)
            ]
            if len(dates) >= 2:
                daily_growth = max(0, dates[0]["rows"] - dates[1]["rows"])
            else:
                daily_growth = None
            return {
                "total_rows": total,
                "recent_dates": dates,
                "estimated_daily_new_rows": daily_growth,
                "storage": "price_daily",
            }

        table = catalog_table("price_snapshots")
        total = _table_row_count(conn, table) or 0
        rows = conn.execute(
            f"""
            SELECT snapshot_date, COUNT(*) AS c
            FROM {table}
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
            LIMIT 10
            """
        ).fetchall()
        dates = [{"date": row["snapshot_date"], "rows": int(row["c"])} for row in rows]
        if len(dates) >= 2:
            recent = dates[0]["rows"]
            prior = dates[1]["rows"]
            daily_growth = max(0, recent - prior)
        else:
            daily_growth = None
        return {"total_rows": total, "recent_dates": dates, "estimated_daily_new_rows": daily_growth}
    except Exception as error:  # noqa: BLE001
        return {"error": str(error)}


def _cm_guide_date_stats(conn) -> dict[str, Any]:
    table = catalog_table("cardmarket_price_guide_daily")
    try:
        rows = conn.execute(
            f"""
            SELECT snapshot_date, COUNT(*) AS c
            FROM {table}
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
            LIMIT 5
            """
        ).fetchall()
        return {"dates": [{"date": row["snapshot_date"], "rows": int(row["c"])} for row in rows]}
    except Exception as error:  # noqa: BLE001
        return {"error": str(error)}


def tech_stack_audit(*, main_db_gb: float, price_snapshots_rows: int) -> dict[str, Any]:
    """Recommandations techno — audit statique, pas de migration auto."""
    sqlite_fit = "good"
    notes: list[str] = []
    if main_db_gb >= 15 or price_snapshots_rows >= 30_000_000:
        sqlite_fit = "stretched"
        notes.append("SQLite reste utilisable mais les requetes full-scan / historiques lourds deviennent couteux.")
    if main_db_gb >= 8:
        notes.append("Prioriser table live du jour + retention tiered sur price_snapshots avant split fichiers.")

    recommended_future = []
    if price_snapshots_rows > 5_000_000:
        recommended_future.append(
            {
                "role": "time_series_prices",
                "options": ["TimescaleDB (PostgreSQL)", "ClickHouse", "DuckDB analytics (fichier par an)"],
                "why": "20M+ lignes de snapshots : partition temporelle, compression, agregats rapides.",
            }
        )
    recommended_future.append(
        {
            "role": "user_app_state",
            "options": ["SQLite dedie (mtg_user.sqlite3)", "PostgreSQL leger"],
            "why": "Collection, wishlist, alertes : petit volume, transactions OLTP — SQLite ideal.",
        }
    )
    recommended_future.append(
        {
            "role": "catalog_reference",
            "options": ["SQLite read-only ATTACH", "PostgreSQL replica"],
            "why": "cards + maps : lecture frequente, mises a jour batch nocturnes.",
        }
    )

    return {
        "current_stack": "SQLite 3 (WAL) — monolithique data/mtg_pwa.sqlite3",
        "shared_catalog_env": os.environ.get("MTG_PWA_PRICES_DB") or None,
        "sqlite_fit": sqlite_fit,
        "multi_db_recommended": main_db_gb >= 6 or price_snapshots_rows >= 3_000_000,
        "migration_urgency": "planned" if main_db_gb >= 8 else "monitor",
        "notes": notes,
        "target_topology": {
            "hot": "live_prices_today + cardmarket_guide_today (truncate/insert quotidien)",
            "warm": "price_snapshots retention 60j/1m/1y + cardmarket_price_guide_daily",
            "cold": "E:\\Backup\\MTG Data (cumul insert-only) + fichiers annuels DuckDB/Parquet (futur)",
            "user": "mtg_user.sqlite3 (collection, wishlist, index, alertes)",
        },
        "recommended_future": recommended_future,
        "verdict": (
            "Rester sur SQLite court terme avec decoupage fichiers + retention ; "
            "envisager PostgreSQL/Timescale ou DuckDB froid si >20 Go ou requetes analytics lentes."
        ),
    }


def collect_db_audit(
    *,
    db_path: Path | str | None = None,
    backup_root: Path | str | None = None,
) -> dict[str, Any]:
    path = Path(db_path or DEFAULT_DB_PATH).resolve()
    backup_dir = Path(backup_root or os.environ.get("MTG_BACKUP_ROOT", DEFAULT_BACKUP_ROOT)).resolve()
    backup_db_path = backup_dir / BACKUP_DB_NAME

    db_files: dict[str, Any] = {"main": {"path": str(path), "exists": path.exists()}}
    if path.exists():
        db_files["main"]["size_gb"] = round(path.stat().st_size / (1024**3), 3)
        wal = path.with_suffix(path.suffix + "-wal")
        shm = path.with_suffix(path.suffix + "-shm")
        if wal.exists():
            db_files["wal"] = {"path": str(wal), "size_gb": round(wal.stat().st_size / (1024**3), 3)}
        if shm.exists():
            db_files["shm"] = {"path": str(shm), "size_mb": round(shm.stat().st_size / (1024**2), 2)}

    shared = shared_prices_db_path()
    if shared and shared.exists():
        db_files["shared_prices"] = {
            "path": str(shared),
            "size_gb": round(shared.stat().st_size / (1024**3), 3),
        }

    backup_info: dict[str, Any] = {
        "root": str(backup_dir),
        "db_path": str(backup_db_path),
        "exists": backup_db_path.exists(),
        "root_exists": backup_dir.exists(),
    }
    if backup_db_path.exists():
        backup_info["size_gb"] = round(backup_db_path.stat().st_size / (1024**3), 3)
    backup_info["dir_size_gb"] = round(_path_size_bytes(backup_dir) / (1024**3), 3) if backup_dir.exists() else 0

    disks: dict[str, Any] = {}
    for label, disk_path in [("data_drive", path.parent), ("backup_drive", backup_dir)]:
        usage = disk_usage(disk_path)
        if usage:
            disks[label] = usage

    tables: dict[str, int | None] = {}
    price_stats: dict[str, Any] = {}
    cm_stats: dict[str, Any] = {}
    if path.exists():
        conn = connect(path)
        init_db(conn)
        try:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for row in table_rows:
                name = row["name"]
                tables[name] = _table_row_count(conn, name)
            price_stats = _price_snapshot_date_stats(conn)
            cm_stats = _cm_guide_date_stats(conn)
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            db_files["main"]["page_count"] = page_count
            db_files["main"]["page_size"] = page_size
            db_files["main"]["logical_size_gb"] = round((page_count * page_size) / (1024**3), 3)
        finally:
            conn.close()

    main_gb = float(db_files.get("main", {}).get("size_gb") or 0)
    ps_rows = int(price_stats.get("total_rows") or tables.get("price_snapshots") or 0)
    backup_gb = float(backup_info.get("size_gb") or 0)
    backup_free = float((disks.get("backup_drive") or {}).get("free_gb") or 0)

    warnings: list[dict[str, Any]] = []

    main_level = _warning_level(
        main_gb,
        info=MAIN_DB_INFO_GB,
        warning=MAIN_DB_WARNING_GB,
        critical=MAIN_DB_CRITICAL_GB,
    )
    if main_level != "ok":
        warnings.append(
            {
                "level": main_level,
                "scope": "main_db",
                "message": f"Base principale {main_gb:.2f} Go (seuils info/warn/crit : {MAIN_DB_INFO_GB}/{MAIN_DB_WARNING_GB}/{MAIN_DB_CRITICAL_GB} Go).",
            }
        )

    if not backup_dir.exists():
        warnings.append(
            {
                "level": "warning",
                "scope": "backup_root",
                "message": f"Dossier backup absent : {backup_dir}",
            }
        )
    elif backup_free and backup_free < BACKUP_DISK_CRITICAL_FREE_GB:
        warnings.append(
            {
                "level": "critical",
                "scope": "backup_disk",
                "message": f"Espace libre backup {backup_free:.1f} Go (< {BACKUP_DISK_CRITICAL_FREE_GB} Go).",
            }
        )
    elif backup_free and backup_free < BACKUP_DISK_WARNING_FREE_GB:
        warnings.append(
            {
                "level": "warning",
                "scope": "backup_disk",
                "message": f"Espace libre backup {backup_free:.1f} Go (< {BACKUP_DISK_WARNING_FREE_GB} Go).",
            }
        )

    if backup_gb >= BACKUP_DB_CRITICAL_GB:
        warnings.append(
            {
                "level": "critical",
                "scope": "backup_db",
                "message": f"Backup cumulatif {backup_gb:.2f} Go (>= {BACKUP_DB_CRITICAL_GB} Go).",
            }
        )
    elif backup_gb >= BACKUP_DB_WARNING_GB:
        warnings.append(
            {
                "level": "warning",
                "scope": "backup_db",
                "message": f"Backup cumulatif {backup_gb:.2f} Go (>= {BACKUP_DB_WARNING_GB} Go).",
            }
        )

    daily_new = price_stats.get("estimated_daily_new_rows")
    projected_month_gb = None
    if daily_new and main_gb > 0 and ps_rows > 0:
        bytes_per_row = (main_gb * (1024**3)) / ps_rows
        projected_month_gb = round((daily_new * 30 * bytes_per_row) / (1024**3), 2)
        if projected_month_gb >= 1.0:
            warnings.append(
                {
                    "level": "info",
                    "scope": "growth",
                    "message": f"Croissance estimee ~{projected_month_gb:.1f} Go/mois (snapshots, heuristique).",
                }
            )

    worst = "ok"
    for item in warnings:
        level = item["level"]
        if level == "critical":
            worst = "critical"
            break
        if level == "warning" and worst not in {"critical"}:
            worst = "warning"
        if level == "info" and worst == "ok":
            worst = "info"

    return {
        "audited_at": utc_now(),
        "audit_date": date.today().isoformat(),
        "uses_shared_catalog": uses_shared_catalog(),
        "db_files": db_files,
        "backup": backup_info,
        "disks": disks,
        "tables": tables,
        "price_snapshots": price_stats,
        "cardmarket_guide": cm_stats,
        "thresholds": {
            "main_db_gb": {
                "info": MAIN_DB_INFO_GB,
                "warning": MAIN_DB_WARNING_GB,
                "critical": MAIN_DB_CRITICAL_GB,
            },
            "backup_disk_free_gb": {
                "warning": BACKUP_DISK_WARNING_FREE_GB,
                "critical": BACKUP_DISK_CRITICAL_FREE_GB,
            },
            "backup_db_gb": {"warning": BACKUP_DB_WARNING_GB, "critical": BACKUP_DB_CRITICAL_GB},
        },
        "warnings": warnings,
        "overall_status": worst,
        "growth_projection_month_gb": projected_month_gb,
        "tech_stack": tech_stack_audit(main_db_gb=main_gb, price_snapshots_rows=ps_rows),
    }
