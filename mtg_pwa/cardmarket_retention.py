from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .database import catalog_table, utc_now

DAILY_RETENTION_DAYS = 60
MONTHLY_RETENTION_DAYS = 365
YEARLY_RETENTION_DAYS = 365 * 5


def compact_cardmarket_guide_history(conn: sqlite3.Connection, *, as_of: date | None = None) -> dict[str, int]:
    """Tiered retention: daily 60d, monthly to 1y, yearly to 5y, purge older."""
    guide_table = catalog_table("cardmarket_price_guide_daily")
    today = as_of or date.today()
    daily_cutoff = (today - timedelta(days=DAILY_RETENTION_DAYS)).isoformat()
    monthly_cutoff = (today - timedelta(days=MONTHLY_RETENTION_DAYS)).isoformat()
    yearly_cutoff = (today - timedelta(days=YEARLY_RETENTION_DAYS)).isoformat()

    deleted_old = conn.execute(
        f"DELETE FROM {guide_table} WHERE snapshot_date < ?",
        (yearly_cutoff,),
    ).rowcount

    deleted_monthly = conn.execute(
        f"""
        DELETE FROM {guide_table}
        WHERE snapshot_date < ?
          AND snapshot_date >= ?
          AND rowid NOT IN (
            SELECT MAX(rowid)
            FROM {guide_table}
            WHERE snapshot_date < ?
              AND snapshot_date >= ?
            GROUP BY id_product, substr(snapshot_date, 1, 7)
          )
        """,
        (daily_cutoff, monthly_cutoff, daily_cutoff, monthly_cutoff),
    ).rowcount

    deleted_yearly = conn.execute(
        f"""
        DELETE FROM {guide_table}
        WHERE snapshot_date < ?
          AND snapshot_date >= ?
          AND rowid NOT IN (
            SELECT MAX(rowid)
            FROM {guide_table}
            WHERE snapshot_date < ?
              AND snapshot_date >= ?
            GROUP BY id_product, substr(snapshot_date, 1, 4)
          )
        """,
        (monthly_cutoff, yearly_cutoff, monthly_cutoff, yearly_cutoff),
    ).rowcount

    conn.commit()
    return {
        "deleted_older_than_5y": deleted_old,
        "deleted_monthly_thinned": deleted_monthly,
        "deleted_yearly_thinned": deleted_yearly,
        "compacted_at": utc_now(),
    }
