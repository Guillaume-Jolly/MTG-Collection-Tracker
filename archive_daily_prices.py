"""Archive today's MTGJSON prices into the local SQLite database."""
from __future__ import annotations

import argparse
import sys

from mtg_pwa.price_archive import archive_daily_prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive MTGJSON daily prices into mtg_pwa.sqlite3.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if today's archive was already completed.",
    )
    args = parser.parse_args()
    try:
        result = archive_daily_prices(force=args.force)
    except Exception as error:  # noqa: BLE001 - CLI should surface archive failures.
        print(f"Erreur: {error}", file=sys.stderr)
        sys.exit(1)
    if result.get("skipped"):
        print(f"Deja archive aujourd'hui ({result.get('archive_date')}).")
        return
    print(
        f"Termine: MTGJSON {result.get('snapshots_written', 0)} snapshots, "
        f"Cardmarket {result.get('cardmarket_rows_written', 0)} lignes "
        f"({result.get('archive_date')})."
    )


if __name__ == "__main__":
    main()
