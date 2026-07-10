from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .database import DEFAULT_DB_PATH, connect, get_app_metadata, init_db, set_app_metadata
from .db_audit import BACKUP_DB_NAME, DEFAULT_BACKUP_ROOT, collect_db_audit, disk_usage

LogCallback = Callable[[str], None] | None

LAST_WEEKLY_BACKUP_DATE_KEY = "last_weekly_backup_date"
LAST_WEEKLY_BACKUP_RUN_ID_KEY = "last_weekly_backup_run_id"
LAST_WEEKLY_BACKUP_FINISHED_KEY = "last_weekly_backup_finished_at"
LAST_WEEKLY_BACKUP_STATS_KEY = "last_weekly_backup_stats_json"

BATCH_SIZE = 25_000

INCREMENTAL_TABLES: tuple[str, ...] = (
    "price_snapshots",
    "cardmarket_price_guide_daily",
    "cards",
    "mtgjson_card_map",
    "mtgjson_price_cache",
    "cardmarket_product_map",
)

SNAPSHOT_TABLES: tuple[str, ...] = (
    "collection_items",
    "wishlist_items",
    "price_alerts",
    "price_alert_events",
    "binder_slots",
    "owned_decks",
    "owned_deck_dismissals",
    "app_metadata",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def backup_db_path(backup_root: Path | str | None = None) -> Path:
    root = Path(backup_root or DEFAULT_BACKUP_ROOT)
    return root / BACKUP_DB_NAME


def weekly_backup_already_done_this_week(conn, *, force: bool, as_of: date | None = None) -> bool:
    if force:
        return False
    last = get_app_metadata(conn, LAST_WEEKLY_BACKUP_DATE_KEY)
    if not last:
        return False
    try:
        last_date = date.fromisoformat(str(last))
    except ValueError:
        return False
    today = as_of or date.today()
    return (today - last_date).days < 7


def init_backup_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS backup_runs (
            run_id TEXT PRIMARY KEY,
            backup_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            source_db_path TEXT NOT NULL,
            rows_incremental INTEGER NOT NULL DEFAULT 0,
            rows_snapshot INTEGER NOT NULL DEFAULT 0,
            backup_size_bytes INTEGER,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS collection_items_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            scryfall_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            finish TEXT NOT NULL,
            condition TEXT,
            language TEXT,
            purchase_price REAL,
            purchase_currency TEXT,
            purchase_date TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (backup_run_id, source_id)
        );

        CREATE TABLE IF NOT EXISTS wishlist_items_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            priority INTEGER,
            max_price_eur REAL,
            notes TEXT,
            auto_alert INTEGER,
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (backup_run_id, source_id)
        );

        CREATE TABLE IF NOT EXISTS price_alerts_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            scryfall_id TEXT NOT NULL,
            finish TEXT NOT NULL,
            direction TEXT,
            threshold_eur REAL,
            active INTEGER,
            triggered_at TEXT,
            created_at TEXT,
            PRIMARY KEY (backup_run_id, source_id)
        );

        CREATE TABLE IF NOT EXISTS price_alert_events_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            alert_id INTEGER,
            scryfall_id TEXT NOT NULL,
            finish TEXT,
            direction TEXT,
            threshold_eur REAL,
            triggered_eur REAL,
            triggered_at TEXT,
            name TEXT,
            PRIMARY KEY (backup_run_id, source_id)
        );

        CREATE TABLE IF NOT EXISTS binder_slots_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            scryfall_id TEXT NOT NULL,
            finish TEXT,
            binder_name TEXT,
            page_number INTEGER,
            slot_number INTEGER,
            condition TEXT,
            quantity INTEGER,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (backup_run_id, source_id)
        );

        CREATE TABLE IF NOT EXISTS owned_decks_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            file_name TEXT NOT NULL,
            owned_at TEXT NOT NULL,
            PRIMARY KEY (backup_run_id, file_name)
        );

        CREATE TABLE IF NOT EXISTS owned_deck_dismissals_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            file_name TEXT NOT NULL,
            dismissed_at TEXT NOT NULL,
            PRIMARY KEY (backup_run_id, file_name)
        );

        CREATE TABLE IF NOT EXISTS app_metadata_history (
            backup_run_id TEXT NOT NULL,
            backup_date TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (backup_run_id, key)
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY,
            scryfall_id TEXT NOT NULL,
            currency TEXT NOT NULL,
            finish TEXT NOT NULL,
            price REAL NOT NULL,
            source TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            source_updated_at TEXT,
            UNIQUE (scryfall_id, currency, finish, source, snapshot_date)
        );

        CREATE TABLE IF NOT EXISTS cards (
            scryfall_id TEXT PRIMARY KEY,
            oracle_id TEXT,
            name TEXT NOT NULL,
            printed_name TEXT,
            lang TEXT,
            set_code TEXT,
            set_name TEXT,
            collector_number TEXT,
            rarity TEXT,
            image_url TEXT,
            scryfall_uri TEXT,
            raw_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mtgjson_card_map (
            scryfall_id TEXT PRIMARY KEY,
            mtgjson_uuid TEXT NOT NULL,
            set_code TEXT,
            collector_number TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mtgjson_price_cache (
            mtgjson_uuid TEXT PRIMARY KEY,
            raw_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cardmarket_product_map (
            id_product INTEGER PRIMARY KEY,
            scryfall_id TEXT NOT NULL UNIQUE,
            set_code TEXT,
            collector_number TEXT,
            mapped_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cardmarket_price_guide_daily (
            id_product INTEGER NOT NULL,
            snapshot_date TEXT NOT NULL,
            trend REAL,
            low_price REAL,
            avg REAL,
            avg1 REAL,
            avg7 REAL,
            avg30 REAL,
            trend_foil REAL,
            low_foil REAL,
            avg_foil REAL,
            avg1_foil REAL,
            avg7_foil REAL,
            avg30_foil REAL,
            guide_version INTEGER,
            guide_created_at TEXT,
            collected_at TEXT NOT NULL,
            PRIMARY KEY (id_product, snapshot_date)
        );

        CREATE INDEX IF NOT EXISTS idx_backup_ps_id ON price_snapshots(id);
        CREATE INDEX IF NOT EXISTS idx_coll_hist_date ON collection_items_history(backup_date);
        """
    )
    conn.commit()


def _copy_incremental_table(
    source: sqlite3.Connection,
    backup: sqlite3.Connection,
    table: str,
    *,
    on_log: LogCallback = None,
) -> int:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if table == "price_snapshots":
        last_id_row = backup.execute("SELECT COALESCE(MAX(id), 0) FROM price_snapshots").fetchone()
        last_id = int(last_id_row[0] if last_id_row else 0)
        total = 0
        while True:
            rows = source.execute(
                f"""
                SELECT id, scryfall_id, currency, finish, price, source, snapshot_date, collected_at, source_updated_at
                FROM {table}
                WHERE id > ?
                ORDER BY id
                LIMIT ?
                """,
                (last_id, BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            backup.executemany(
                """
                INSERT OR IGNORE INTO price_snapshots (
                    id, scryfall_id, currency, finish, price, source, snapshot_date, collected_at, source_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in rows],
            )
            backup.commit()
            last_id = int(rows[-1]["id"])
            total += len(rows)
            log(f"  {table}: +{len(rows)} (max id {last_id}, cumul {total})")
        return total

    if table == "cards":
        cols = (
            "scryfall_id, oracle_id, name, printed_name, lang, set_code, set_name, "
            "collector_number, rarity, image_url, scryfall_uri, raw_json, updated_at"
        )
        rows = source.execute(f"SELECT {cols} FROM {table}").fetchall()
        if not rows:
            return 0
        backup.executemany(
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({','.join('?' for _ in range(13))})",
            [tuple(row) for row in rows],
        )
        backup.commit()
        log(f"  {table}: {len(rows)} lignes source (insert ignore)")
        return len(rows)

    if table == "cardmarket_price_guide_daily":
        cols = (
            "id_product, snapshot_date, trend, low_price, avg, avg1, avg7, avg30, "
            "trend_foil, low_foil, avg_foil, avg1_foil, avg7_foil, avg30_foil, "
            "guide_version, guide_created_at, collected_at"
        )
        rows = source.execute(f"SELECT {cols} FROM {table}").fetchall()
        if not rows:
            return 0
        backup.executemany(
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({','.join('?' for _ in range(17))})",
            [tuple(row) for row in rows],
        )
        backup.commit()
        log(f"  {table}: {len(rows)} lignes source (insert ignore)")
        return len(rows)

    col_rows = source.execute(f"PRAGMA table_info({table})").fetchall()
    cols = [row["name"] for row in col_rows]
    if not cols:
        return 0
    col_list = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    rows = source.execute(f"SELECT {col_list} FROM {table}").fetchall()
    if not rows:
        return 0
    backup.executemany(
        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
        [tuple(row) for row in rows],
    )
    backup.commit()
    log(f"  {table}: {len(rows)} lignes source (insert ignore)")
    return len(rows)


def _snapshot_table(
    source: sqlite3.Connection,
    backup: sqlite3.Connection,
    table: str,
    *,
    run_id: str,
    backup_date: str,
    on_log: LogCallback = None,
) -> int:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if table == "collection_items":
        rows = source.execute(
            """
            SELECT id, scryfall_id, quantity, finish, condition, language,
                   purchase_price, purchase_currency, purchase_date, notes, created_at, updated_at
            FROM collection_items
            """
        ).fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO collection_items_history (
                backup_run_id, backup_date, source_id, scryfall_id, quantity, finish, condition, language,
                purchase_price, purchase_currency, purchase_date, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    backup_date,
                    row["id"],
                    row["scryfall_id"],
                    row["quantity"],
                    row["finish"],
                    row["condition"],
                    row["language"],
                    row["purchase_price"],
                    row["purchase_currency"],
                    row["purchase_date"],
                    row["notes"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows
            ],
        )
        backup.commit()
        log(f"  snapshot collection_items: {len(rows)} lignes")
        return len(rows)

    if table == "wishlist_items":
        rows = source.execute(
            "SELECT id, scryfall_id, finish, quantity, priority, max_price_eur, notes, created_at, updated_at FROM wishlist_items"
        ).fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO wishlist_items_history (
                backup_run_id, backup_date, source_id, scryfall_id, finish, quantity, priority,
                max_price_eur, notes, auto_alert, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    backup_date,
                    row["id"],
                    row["scryfall_id"],
                    row["finish"],
                    row["quantity"],
                    row["priority"],
                    row["max_price_eur"],
                    row["notes"],
                    None,
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows
            ],
        )
        backup.commit()
        log(f"  snapshot wishlist_items: {len(rows)} lignes")
        return len(rows)

    if table == "price_alerts":
        rows = source.execute(
            "SELECT id, scryfall_id, finish, direction, threshold_eur, active, triggered_at, created_at FROM price_alerts"
        ).fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO price_alerts_history (
                backup_run_id, backup_date, source_id, scryfall_id, finish, direction,
                threshold_eur, active, triggered_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    backup_date,
                    row["id"],
                    row["scryfall_id"],
                    row["finish"],
                    row["direction"],
                    row["threshold_eur"],
                    row["active"],
                    row["triggered_at"],
                    row["created_at"],
                )
                for row in rows
            ],
        )
        backup.commit()
        return len(rows)

    if table == "price_alert_events":
        rows = source.execute(
            """
            SELECT id, alert_id, scryfall_id, finish, direction, threshold_eur, triggered_eur, triggered_at, name
            FROM price_alert_events
            """
        ).fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO price_alert_events_history (
                backup_run_id, backup_date, source_id, alert_id, scryfall_id, finish, direction,
                threshold_eur, triggered_eur, triggered_at, name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    backup_date,
                    row["id"],
                    row["alert_id"],
                    row["scryfall_id"],
                    row["finish"],
                    row["direction"],
                    row["threshold_eur"],
                    row["triggered_eur"],
                    row["triggered_at"],
                    row["name"],
                )
                for row in rows
            ],
        )
        backup.commit()
        return len(rows)

    if table == "binder_slots":
        rows = source.execute(
            """
            SELECT id, scryfall_id, finish, binder_name, page_number, slot_number, condition, quantity, notes, created_at, updated_at
            FROM binder_slots
            """
        ).fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO binder_slots_history (
                backup_run_id, backup_date, source_id, scryfall_id, finish, binder_name, page_number,
                slot_number, condition, quantity, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    backup_date,
                    row["id"],
                    row["scryfall_id"],
                    row["finish"],
                    row["binder_name"],
                    row["page_number"],
                    row["slot_number"],
                    row["condition"],
                    row["quantity"],
                    row["notes"],
                    row["created_at"],
                    row["updated_at"],
                )
                for row in rows
            ],
        )
        backup.commit()
        return len(rows)

    if table == "owned_decks":
        rows = source.execute("SELECT file_name, owned_at FROM owned_decks").fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO owned_decks_history (backup_run_id, backup_date, file_name, owned_at)
            VALUES (?, ?, ?, ?)
            """,
            [(run_id, backup_date, row["file_name"], row["owned_at"]) for row in rows],
        )
        backup.commit()
        return len(rows)

    if table == "owned_deck_dismissals":
        rows = source.execute("SELECT file_name, dismissed_at FROM owned_deck_dismissals").fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO owned_deck_dismissals_history (backup_run_id, backup_date, file_name, dismissed_at)
            VALUES (?, ?, ?, ?)
            """,
            [(run_id, backup_date, row["file_name"], row["dismissed_at"]) for row in rows],
        )
        backup.commit()
        return len(rows)

    if table == "app_metadata":
        rows = source.execute("SELECT key, value, updated_at FROM app_metadata").fetchall()
        if not rows:
            return 0
        backup.executemany(
            """
            INSERT OR IGNORE INTO app_metadata_history (backup_run_id, backup_date, key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(run_id, backup_date, row["key"], row["value"], row["updated_at"]) for row in rows],
        )
        backup.commit()
        return len(rows)

    return 0


def run_weekly_backup(
    *,
    db_path: Path | str | None = None,
    backup_root: Path | str | None = None,
    force: bool = False,
    on_log: LogCallback = None,
) -> dict[str, Any]:
    import json

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)
        else:
            print(msg, flush=True)

    source_path = Path(db_path or DEFAULT_DB_PATH).resolve()
    root = Path(backup_root or DEFAULT_BACKUP_ROOT).resolve()
    dest_path = backup_db_path(root)
    run_id = date.today().isoformat().replace("-", "") + "-" + uuid.uuid4().hex[:8]
    backup_date = date.today().isoformat()
    started_at = utc_now()
    result: dict[str, Any] = {
        "run_id": run_id,
        "backup_date": backup_date,
        "started_at": started_at,
        "finished_at": None,
        "skipped": False,
        "error": None,
        "source_db_path": str(source_path),
        "backup_db_path": str(dest_path),
        "rows_incremental": 0,
        "rows_snapshot": 0,
    }

    if not source_path.exists():
        result["error"] = f"Base source introuvable: {source_path}"
        return result

    usage = disk_usage(root)
    if usage and usage["free_gb"] < 5:
        result["error"] = f"Espace disque insuffisant sur {root} ({usage['free_gb']} Go libres)"
        return result

    source_meta = connect(source_path)
    init_db(source_meta)
    try:
        if weekly_backup_already_done_this_week(source_meta, force=force):
            result["skipped"] = True
            result["finished_at"] = utc_now()
            log(f"Backup hebdo deja effectue cette semaine ({get_app_metadata(source_meta, LAST_WEEKLY_BACKUP_DATE_KEY)}).")
            return result
    finally:
        source_meta.close()

    root.mkdir(parents=True, exist_ok=True)
    backup = sqlite3.connect(dest_path, timeout=60)
    backup.row_factory = sqlite3.Row
    backup.execute("PRAGMA journal_mode = WAL")
    backup.execute("PRAGMA synchronous = NORMAL")
    init_backup_schema(backup)

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=60)
    source.row_factory = sqlite3.Row

    try:
        backup.execute(
            """
            INSERT INTO backup_runs (run_id, backup_date, started_at, source_db_path)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, backup_date, started_at, str(source_path)),
        )
        backup.commit()

        log(f"Backup hebdo {run_id} -> {dest_path}")
        log("Copie incrementielle (insert only)...")
        inc_total = 0
        for table in INCREMENTAL_TABLES:
            try:
                inc_total += _copy_incremental_table(source, backup, table, on_log=log)
            except sqlite3.OperationalError as error:
                if "no such table" in str(error).lower():
                    log(f"  {table}: absente, ignoree")
                    continue
                raise

        log("Snapshots hebdo (historique collection / app)...")
        snap_total = 0
        for table in SNAPSHOT_TABLES:
            try:
                snap_total += _snapshot_table(
                    source, backup, table, run_id=run_id, backup_date=backup_date, on_log=log
                )
            except sqlite3.OperationalError as error:
                if "no such table" in str(error).lower():
                    log(f"  snapshot {table}: absente, ignoree")
                    continue
                raise

        finished_at = utc_now()
        size_bytes = dest_path.stat().st_size if dest_path.exists() else 0
        backup.execute(
            """
            UPDATE backup_runs
            SET finished_at = ?, rows_incremental = ?, rows_snapshot = ?, backup_size_bytes = ?
            WHERE run_id = ?
            """,
            (finished_at, inc_total, snap_total, size_bytes, run_id),
        )
        backup.commit()

        result["rows_incremental"] = inc_total
        result["rows_snapshot"] = snap_total
        result["finished_at"] = finished_at
        result["backup_size_gb"] = round(size_bytes / (1024**3), 3)

        meta = connect(source_path)
        init_db(meta)
        try:
            stats = {
                "run_id": run_id,
                "rows_incremental": inc_total,
                "rows_snapshot": snap_total,
                "backup_size_gb": result["backup_size_gb"],
            }
            set_app_metadata(meta, LAST_WEEKLY_BACKUP_DATE_KEY, backup_date)
            set_app_metadata(meta, LAST_WEEKLY_BACKUP_RUN_ID_KEY, run_id)
            set_app_metadata(meta, LAST_WEEKLY_BACKUP_FINISHED_KEY, finished_at)
            set_app_metadata(meta, LAST_WEEKLY_BACKUP_STATS_KEY, json.dumps(stats))
            meta.commit()
        finally:
            meta.close()

        audit = collect_db_audit(db_path=source_path, backup_root=root)
        result["audit"] = {
            "overall_status": audit["overall_status"],
            "warnings": audit["warnings"],
            "backup_size_gb": audit["backup"].get("size_gb"),
            "backup_disk_free_gb": (audit.get("disks") or {}).get("backup_drive", {}).get("free_gb"),
        }
        log(
            f"Termine: +{inc_total} incrementiel, {snap_total} snapshot, "
            f"backup {result['backup_size_gb']} Go"
        )
        for warning in audit.get("warnings") or []:
            log(f"  [{warning['level']}] {warning['message']}")
    except Exception as error:  # noqa: BLE001
        result["error"] = str(error)
        result["finished_at"] = utc_now()
        try:
            backup.execute(
                "UPDATE backup_runs SET finished_at = ?, error = ? WHERE run_id = ?",
                (result["finished_at"], str(error), run_id),
            )
            backup.commit()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        source.close()
        backup.close()

    return result


def weekly_backup_status(*, db_path: Path | str | None = None, backup_root: Path | str | None = None) -> dict[str, Any]:
    import json

    path = Path(db_path or DEFAULT_DB_PATH)
    root = Path(backup_root or DEFAULT_BACKUP_ROOT)
    dest = backup_db_path(root)
    audit = collect_db_audit(db_path=path, backup_root=root)

    last_date = None
    last_stats = None
    if path.exists():
        conn = connect(path)
        init_db(conn)
        try:
            last_date = get_app_metadata(conn, LAST_WEEKLY_BACKUP_DATE_KEY)
            raw_stats = get_app_metadata(conn, LAST_WEEKLY_BACKUP_STATS_KEY)
            if raw_stats:
                try:
                    last_stats = json.loads(raw_stats)
                except json.JSONDecodeError:
                    last_stats = None
        finally:
            conn.close()

    due = True
    if last_date:
        try:
            due = (date.today() - date.fromisoformat(str(last_date))).days >= 7
        except ValueError:
            due = True

    return {
        "last_backup_date": last_date,
        "last_backup_stats": last_stats,
        "due": due,
        "backup_db_path": str(dest),
        "backup_exists": dest.exists(),
        "audit_summary": {
            "overall_status": audit["overall_status"],
            "main_db_gb": audit["db_files"].get("main", {}).get("size_gb"),
            "backup_gb": audit["backup"].get("size_gb"),
            "warnings_count": len(audit.get("warnings") or []),
        },
    }
