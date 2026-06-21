from __future__ import annotations

import argparse

from mtg_pwa.server import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the MTG collection PWA MVP.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind, defaults to 127.0.0.1.")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind, defaults to 8000.")
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
