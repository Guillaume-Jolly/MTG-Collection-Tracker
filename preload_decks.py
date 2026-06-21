from __future__ import annotations

import argparse
import sys

from mtg_pwa.preload import preload_commander_decks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precharge localement decks Commander, cartes Scryfall, prix MTGJSON et images."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limiter le nombre de decks (par defaut: tous les Commander).",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Ne pas telecharger les images des cartes.",
    )
    args = parser.parse_args()

    try:
        result = preload_commander_decks(
            limit=args.limit,
            commander_only=True,
            download_images=not args.skip_images,
        )
    except Exception as error:  # noqa: BLE001 - CLI should report preload failures clearly.
        print(f"Erreur de prechargement: {error}", file=sys.stderr)
        return 1

    print("")
    print("Resume:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0 if result.get("error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
