"""Table price_daily — prix US/Scryfall compacts (1 ligne / carte / jour)."""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .database import catalog_table, utc_now

# mtgjson-cardmarket exclu — CM via cardmarket_price_guide_daily
SOURCE_FINISH_COLUMN: dict[tuple[str, str], str] = {
    ("mtgjson-cardkingdom", "nonfoil"): "ck_nonfoil",
    ("mtgjson-cardkingdom", "foil"): "ck_foil",
    ("mtgjson-cardkingdom", "etched"): "ck_etched",
    ("mtgjson-tcgplayer", "nonfoil"): "tcg_nonfoil",
    ("mtgjson-tcgplayer", "foil"): "tcg_foil",
    ("mtgjson-tcgplayer", "etched"): "tcg_etched",
    ("mtgjson-manapool", "nonfoil"): "mp_nonfoil",
    ("mtgjson-manapool", "foil"): "mp_foil",
    ("mtgjson-manapool", "etched"): "mp_etched",
    ("scryfall-cardmarket", "nonfoil"): "sf_cm_nonfoil",
    ("scryfall-cardmarket", "foil"): "sf_cm_foil",
    ("scryfall-cardmarket", "etched"): "sf_cm_etched",
}

PRICE_DAILY_VALUE_COLUMNS: tuple[str, ...] = tuple(sorted(set(SOURCE_FINISH_COLUMN.values())))

COLUMN_TO_SOURCE_FINISH: dict[str, tuple[str, str]] = {
    column: source_finish for source_finish, column in SOURCE_FINISH_COLUMN.items()
}

SOURCE_FROM_COLUMN: dict[str, tuple[str, str, str]] = {
    "ck_nonfoil": ("mtgjson-cardkingdom", "nonfoil", "USD"),
    "ck_foil": ("mtgjson-cardkingdom", "foil", "USD"),
    "ck_etched": ("mtgjson-cardkingdom", "etched", "USD"),
    "tcg_nonfoil": ("mtgjson-tcgplayer", "nonfoil", "USD"),
    "tcg_foil": ("mtgjson-tcgplayer", "foil", "USD"),
    "tcg_etched": ("mtgjson-tcgplayer", "etched", "USD"),
    "mp_nonfoil": ("mtgjson-manapool", "nonfoil", "USD"),
    "mp_foil": ("mtgjson-manapool", "foil", "USD"),
    "mp_etched": ("mtgjson-manapool", "etched", "USD"),
    "sf_cm_nonfoil": ("scryfall-cardmarket", "nonfoil", "EUR"),
    "sf_cm_foil": ("scryfall-cardmarket", "foil", "EUR"),
    "sf_cm_etched": ("scryfall-cardmarket", "etched", "EUR"),
}

# Prix US (MTGJSON) ignores — l'utilisateur ne suit que Cardmarket / EUR.
EXCLUDED_SNAPSHOT_SOURCES = frozenset(
    {
        "mtgjson-cardmarket",
        "mtgjson-cardkingdom",
        "mtgjson-tcgplayer",
        "mtgjson-manapool",
    }
)

EUR_ONLY_VALUE_COLUMNS: tuple[str, ...] = tuple(
    column for column in PRICE_DAILY_VALUE_COLUMNS if column.startswith("sf_cm_")
)


def active_price_daily_columns() -> tuple[str, ...]:
    return EUR_ONLY_VALUE_COLUMNS


def price_daily_table() -> str:
    return catalog_table("price_daily")


def ensure_price_daily_schema(conn) -> None:
    cols_sql = ",\n            ".join(f"{col} REAL" for col in PRICE_DAILY_VALUE_COLUMNS)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {price_daily_table()} (
            snapshot_date TEXT NOT NULL,
            scryfall_id TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            source_updated_at TEXT,
            {cols_sql},
            PRIMARY KEY (snapshot_date, scryfall_id)
        )
        """
    )
    info = conn.execute(f"PRAGMA table_info({price_daily_table()})").fetchall()
    column_names = {row[1] for row in info}
    if "source_updated_at" not in column_names:
        conn.execute(f"ALTER TABLE {price_daily_table()} ADD COLUMN source_updated_at TEXT")
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_price_daily_card_date
        ON {price_daily_table()}(scryfall_id, snapshot_date)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_price_daily_date
        ON {price_daily_table()}(snapshot_date)
        """
    )


def uses_price_daily_storage(conn) -> bool:
    from .database import catalog_object_type

    return catalog_object_type(conn, "price_snapshots") == "view"


def reads_price_daily(conn) -> bool:
    from .database import catalog_object_type

    return catalog_object_type(conn, "price_daily") == "table" or uses_price_daily_storage(conn)


def _finish_suffix(finish: str) -> str:
    return finish if finish in ("nonfoil", "foil", "etched") else "nonfoil"


def eur_column_for_finish(finish: str) -> str:
    return f"sf_cm_{_finish_suffix(finish)}"


def column_for_chart_source(source: str, finish: str) -> str | None:
    if source in EXCLUDED_SNAPSHOT_SOURCES:
        return None
    if source == "cardmarket-guide":
        return None
    return SOURCE_FINISH_COLUMN.get((source, finish))


def latest_scryfall_cm_price(conn, scryfall_id: str, finish: str) -> tuple[float, str] | None:
    column = eur_column_for_finish(finish)
    table = price_daily_table()
    row = conn.execute(
        f"""
        SELECT {column} AS price, snapshot_date
        FROM {table}
        WHERE scryfall_id = ? AND {column} IS NOT NULL AND {column} > 0
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        (scryfall_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0]), str(row[1])


def batch_latest_eur_prices(
    conn,
    pairs: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], tuple[float, str]]:
    wanted = {(scryfall_id, finish) for scryfall_id, finish in pairs if scryfall_id and finish}
    if not wanted:
        return {}
    by_finish: dict[str, list[str]] = {}
    for scryfall_id, finish in wanted:
        by_finish.setdefault(finish, []).append(scryfall_id)
    table = price_daily_table()
    result: dict[tuple[str, str], tuple[float, str]] = {}
    for finish, scryfall_ids in by_finish.items():
        column = eur_column_for_finish(finish)
        for index in range(0, len(scryfall_ids), 400):
            chunk = scryfall_ids[index : index + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT d.scryfall_id, d.{column} AS price
                FROM {table} d
                INNER JOIN (
                    SELECT scryfall_id, MAX(snapshot_date) AS max_date
                    FROM {table}
                    WHERE scryfall_id IN ({placeholders})
                      AND {column} IS NOT NULL
                      AND {column} > 0
                    GROUP BY scryfall_id
                ) latest
                  ON latest.scryfall_id = d.scryfall_id
                 AND latest.max_date = d.snapshot_date
                WHERE d.scryfall_id IN ({placeholders})
                  AND d.{column} IS NOT NULL
                  AND d.{column} > 0
                """,
                (*chunk, *chunk),
            ).fetchall()
            for row in rows:
                key = (row[0], finish)
                if key in wanted and key not in result:
                    result[key] = (float(row[1]), "scryfall-cardmarket")
    return result


def daily_stats_by_date(conn, *, limit: int = 10) -> list[dict[str, Any]]:
    cell_sum = " + ".join(f"({column} IS NOT NULL)" for column in active_price_daily_columns())
    rows = conn.execute(
        f"""
        SELECT snapshot_date, SUM({cell_sum}) AS cells, COUNT(*) AS cards
        FROM {price_daily_table()}
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"date": row[0], "cells": int(row[1] or 0), "cards": int(row[2])}
        for row in rows
    ]


def scryfall_ids_priced_on_daily_date(conn, snapshot_date: str, column: str) -> list[str]:
    if column not in COLUMN_TO_SOURCE_FINISH:
        return []
    rows = conn.execute(
        f"""
        SELECT DISTINCT scryfall_id
        FROM {price_daily_table()}
        WHERE snapshot_date = ?
          AND {column} IS NOT NULL
          AND {column} > 0
        """,
        (snapshot_date,),
    ).fetchall()
    return [row[0] for row in rows]


def market_mover_rows_from_daily_column(
    conn,
    *,
    column: str,
    start_date: str,
    end_date: str,
    eligible_set_codes: frozenset[str],
) -> list[Any]:
    if column not in COLUMN_TO_SOURCE_FINISH or not eligible_set_codes:
        return []
    from .database import catalog_table

    table = price_daily_table()
    cards_table = catalog_table("cards")
    codes = tuple(sorted(eligible_set_codes))
    set_placeholders = ",".join("?" for _ in codes)
    return conn.execute(
        f"""
        WITH eligible_cards AS (
            SELECT scryfall_id
            FROM {cards_table}
            WHERE upper(set_code) IN ({set_placeholders})
        )
        SELECT s.scryfall_id,
               s.{column} AS start_price,
               e.{column} AS end_price
        FROM eligible_cards ec
        INNER JOIN {table} s
                ON s.scryfall_id = ec.scryfall_id
               AND s.snapshot_date = ?
               AND s.{column} IS NOT NULL
               AND s.{column} > 0
        INNER JOIN {table} e
                ON e.scryfall_id = ec.scryfall_id
               AND e.snapshot_date = ?
               AND e.{column} IS NOT NULL
               AND e.{column} > 0
        """,
        (*codes, start_date, end_date),
    ).fetchall()


def pre_period_stats_from_daily(
    conn,
    scryfall_ids: list[str],
    *,
    column: str,
    before_date: str,
    cutoff_date: str,
) -> dict[str, dict[str, float]]:
    if not scryfall_ids or column not in COLUMN_TO_SOURCE_FINISH:
        return {}
    table = price_daily_table()
    stats: dict[str, dict[str, float]] = {}
    for index in range(0, len(scryfall_ids), 400):
        chunk = scryfall_ids[index : index + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT scryfall_id,
                   MIN({column}) AS min_price,
                   MAX({column}) AS max_price,
                   AVG({column}) AS avg_price,
                   COUNT({column}) AS point_count
            FROM {table}
            WHERE scryfall_id IN ({placeholders})
              AND snapshot_date < ?
              AND snapshot_date >= ?
              AND {column} IS NOT NULL
              AND {column} > 0
            GROUP BY scryfall_id
            """,
            (*chunk, before_date, cutoff_date),
        ).fetchall()
        for row in rows:
            stats[row[0]] = {
                "min_price": float(row[1]),
                "max_price": float(row[2]),
                "avg_price": float(row[3] or 0),
                "point_count": float(row[4]),
            }
    return stats


def sync_price_daily_metadata(conn) -> None:
    from .database import set_app_metadata, utc_now

    set_app_metadata(conn, "price_daily_cell_count", str(count_narrow_price_cells(conn)))
    max_row = conn.execute(f"SELECT MAX(snapshot_date) FROM {price_daily_table()}").fetchone()
    if max_row and max_row[0]:
        set_app_metadata(conn, "price_daily_max_date", str(max_row[0]))
    set_app_metadata(conn, "price_daily_stats_at", utc_now())


def column_for_point(source: str, finish: str) -> str | None:
    if source in EXCLUDED_SNAPSHOT_SOURCES:
        return None
    if source.startswith("scryfall-cardmarket-en-print:"):
        return SOURCE_FINISH_COLUMN.get(("scryfall-cardmarket", finish))
    return SOURCE_FINISH_COLUMN.get((source, finish))


def upsert_price_daily_points(conn, points: Iterable[dict[str, Any]]) -> int:
    ensure_price_daily_schema(conn)
    table = price_daily_table()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for point in points:
        source = str(point.get("source") or "")
        finish = str(point.get("finish") or "nonfoil")
        column = column_for_point(source, finish)
        if column is None:
            continue
        snapshot_date = str(point.get("snapshot_date") or date.today().isoformat())
        scryfall_id = str(point.get("scryfall_id") or "")
        if not scryfall_id:
            continue
        key = (snapshot_date, scryfall_id)
        row = grouped.setdefault(
            key,
            {
                "snapshot_date": snapshot_date,
                "scryfall_id": scryfall_id,
                "collected_at": point.get("collected_at") or utc_now(),
            },
        )
        row[column] = float(point["price"])
        if point.get("collected_at"):
            row["collected_at"] = point["collected_at"]
        if point.get("source_updated_at"):
            row["source_updated_at"] = point["source_updated_at"]

    if not grouped:
        return 0

    columns = ["snapshot_date", "scryfall_id", "collected_at", "source_updated_at", *PRICE_DAILY_VALUE_COLUMNS]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{col}=excluded.{col}" for col in PRICE_DAILY_VALUE_COLUMNS)
    updates += ", collected_at=excluded.collected_at, source_updated_at=excluded.source_updated_at"
    sql = f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(snapshot_date, scryfall_id) DO UPDATE SET {updates}
    """
    rows = []
    for payload in grouped.values():
        rows.append(
            [
                payload["snapshot_date"],
                payload["scryfall_id"],
                payload["collected_at"],
                payload.get("source_updated_at"),
                *[payload.get(col) for col in PRICE_DAILY_VALUE_COLUMNS],
            ]
        )
    conn.executemany(sql, rows)
    return len(rows)


def build_price_snapshots_view_sql(view_name: str = "price_snapshots") -> str:
    table = price_daily_table()
    unions: list[str] = []
    for column in active_price_daily_columns():
        source, finish, currency = SOURCE_FROM_COLUMN[column]
        unions.append(
            f"""
            SELECT
                NULL AS id,
                scryfall_id,
                '{currency}' AS currency,
                '{finish}' AS finish,
                {column} AS price,
                '{source}' AS source,
                snapshot_date,
                collected_at,
                NULL AS source_updated_at
            FROM {table}
            WHERE {column} IS NOT NULL
            """
        )
    body = "\nUNION ALL\n".join(unions)
    return f"CREATE VIEW {view_name} AS {body}"


def daily_history_columns_for_finish(finish: str) -> tuple[str, ...]:
    return tuple(
        column
        for column in PRICE_DAILY_VALUE_COLUMNS
        if COLUMN_TO_SOURCE_FINISH[column][1] == finish
    )


def daily_snapshot_history_points(conn, scryfall_id: str, finish: str) -> list[dict[str, Any]]:
    columns = tuple(
        column
        for column in daily_history_columns_for_finish(finish)
        if column in active_price_daily_columns()
    )
    if not columns:
        return []
    table = price_daily_table()
    select_cols = ", ".join(columns)
    rows = conn.execute(
        f"""
        SELECT snapshot_date, collected_at, {select_cols}
        FROM {table}
        WHERE scryfall_id = ?
        ORDER BY snapshot_date ASC, collected_at ASC
        """,
        (scryfall_id,),
    ).fetchall()
    points: list[dict[str, Any]] = []
    for row in rows:
        for column in columns:
            price = row[column]
            if price is None:
                continue
            source, row_finish, currency = SOURCE_FROM_COLUMN[column]
            points.append(
                {
                    "currency": currency,
                    "finish": row_finish,
                    "price": float(price),
                    "source": source,
                    "snapshot_date": row["snapshot_date"],
                    "collected_at": row["collected_at"],
                }
            )
    return points


def legacy_cardmarket_history_points(conn, scryfall_id: str, finish: str) -> list[dict[str, Any]]:
    from .database import catalog_object_type, catalog_table

    tables: list[str] = []
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone():
        tables.append("price_snapshots_legacy")
    if catalog_object_type(conn, "price_snapshots") == "table":
        tables.append(catalog_table("price_snapshots"))

    points: list[dict[str, Any]] = []
    for table in tables:
        rows = conn.execute(
            f"""
            SELECT currency, finish, price, source, snapshot_date, collected_at
            FROM {table}
            WHERE scryfall_id = ?
              AND finish = ?
              AND source = 'mtgjson-cardmarket'
            ORDER BY snapshot_date ASC, collected_at ASC
            """,
            (scryfall_id, finish),
        ).fetchall()
        points.extend(
            {
                "currency": row["currency"],
                "finish": row["finish"],
                "price": float(row["price"]),
                "source": row["source"],
                "snapshot_date": row["snapshot_date"],
                "collected_at": row["collected_at"],
            }
            for row in rows
        )
    return points


def count_narrow_price_cells(conn) -> int:
    parts = [f"({column} IS NOT NULL)" for column in active_price_daily_columns()]
    row = conn.execute(
        f"SELECT SUM({' + '.join(parts)}) FROM {price_daily_table()}"
    ).fetchone()
    return int(row[0] or 0)


def price_daily_date_bounds_for_columns(conn, columns: Iterable[str]) -> tuple[str, str] | None:
    cols = [column for column in columns if column in COLUMN_TO_SOURCE_FINISH]
    if not cols:
        return None
    predicates = " OR ".join(f"{column} IS NOT NULL" for column in cols)
    row = conn.execute(
        f"""
        SELECT MIN(snapshot_date) AS start_date, MAX(snapshot_date) AS end_date
        FROM {price_daily_table()}
        WHERE {predicates}
        """
    ).fetchone()
    if row is None or not row[1]:
        return None
    start_date = row[0] or row[1]
    return str(start_date), str(row[1])


def migrate_snapshots_to_daily(conn, *, on_progress=None) -> dict[str, Any]:
    from .database import catalog_table

    ensure_price_daily_schema(conn)
    snapshots = catalog_table("price_snapshots")
    legacy_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone()
    if legacy_check:
        snapshots = "price_snapshots_legacy"

    dates = [
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT snapshot_date FROM {snapshots}
            WHERE source NOT IN ('mtgjson-cardmarket')
              AND source NOT LIKE 'scryfall-cardmarket-en-print:%'
            ORDER BY snapshot_date
            """
        ).fetchall()
    ]

    agg_parts = []
    for column in PRICE_DAILY_VALUE_COLUMNS:
        source, finish = COLUMN_TO_SOURCE_FINISH[column]
        agg_parts.append(
            f"MAX(CASE WHEN source = '{source}' AND finish = '{finish}' THEN price END) AS {column}"
        )
    agg_sql = ", ".join(agg_parts)
    inserted_total = 0
    table = price_daily_table()

    for index, snapshot_date in enumerate(dates, start=1):
        conn.execute(
            f"""
            INSERT INTO {table} (
                snapshot_date, scryfall_id, collected_at, {", ".join(PRICE_DAILY_VALUE_COLUMNS)}
            )
            SELECT
                snapshot_date,
                scryfall_id,
                MAX(collected_at),
                {agg_sql}
            FROM {snapshots}
            WHERE snapshot_date = ?
              AND source NOT IN ('mtgjson-cardmarket')
              AND source NOT LIKE 'scryfall-cardmarket-en-print:%'
            GROUP BY snapshot_date, scryfall_id
            ON CONFLICT(snapshot_date, scryfall_id) DO UPDATE SET
                collected_at=excluded.collected_at,
                {", ".join(f"{col}=COALESCE(excluded.{col}, {table}.{col})" for col in PRICE_DAILY_VALUE_COLUMNS)}
            """,
            (snapshot_date,),
        )
        conn.commit()
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE snapshot_date = ?",
            (snapshot_date,),
        ).fetchone()[0]
        inserted_total = int(count)
        if on_progress:
            on_progress(index, len(dates), snapshot_date, inserted_total)

    return {"dates_processed": len(dates), "daily_rows": inserted_total}


def install_price_snapshots_view(conn) -> None:
    view_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='price_snapshots'"
    ).fetchone()
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots'"
    ).fetchone()
    legacy_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_snapshots_legacy'"
    ).fetchone()

    if table_exists and not legacy_exists:
        conn.execute("ALTER TABLE price_snapshots RENAME TO price_snapshots_legacy")
        conn.commit()

    if view_exists:
        conn.execute("DROP VIEW price_snapshots")
    conn.execute(build_price_snapshots_view_sql("price_snapshots"))
    conn.commit()


def drop_legacy_snapshot_indexes(conn) -> None:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='index'
          AND tbl_name='price_snapshots_legacy'
          AND name NOT LIKE 'sqlite_autoindex%'
        """
    ).fetchall()
    for row in rows:
        conn.execute(f"DROP INDEX IF EXISTS {row[0]}")
    conn.commit()


def _legacy_active_source_predicate() -> str:
    active_sources = sorted(
        {
            COLUMN_TO_SOURCE_FINISH[column][0]
            for column in active_price_daily_columns()
        }
    )
    quoted = ", ".join(f"'{source}'" for source in active_sources)
    return f"source IN ({quoted})"


def verify_migration(conn) -> dict[str, Any]:
    snapshots = "price_snapshots_legacy"
    active_predicate = _legacy_active_source_predicate()
    legacy_narrow_rows = conn.execute(
        f"""
        SELECT COUNT(*) FROM {snapshots}
        WHERE source NOT IN ('mtgjson-cardmarket')
          AND source NOT LIKE 'scryfall-cardmarket-en-print:%'
        """
    ).fetchone()[0]
    legacy_active_rows = conn.execute(
        f"SELECT COUNT(*) FROM {snapshots} WHERE {active_predicate}"
    ).fetchone()[0]
    daily_cells = count_narrow_price_cells(conn)
    view_rows = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    return {
        "legacy_narrow_rows": int(legacy_narrow_rows),
        "legacy_active_rows": int(legacy_active_rows),
        "daily_price_cells": int(daily_cells),
        "view_narrow_rows": int(view_rows),
        "match": int(daily_cells) == int(view_rows)
        and int(daily_cells) >= int(legacy_active_rows),
    }
