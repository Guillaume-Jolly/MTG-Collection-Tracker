from __future__ import annotations

import argparse
import os
import socket
import sys

from mtg_pwa.server import run


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the MTG collection PWA MVP.")
    parser.add_argument("--host", default=os.environ.get("MTG_PWA_HOST", "127.0.0.1"), help="Host to bind.")
    default_port = int(os.environ.get("MTG_PWA_PORT", "8000"))
    parser.add_argument("--port", default=default_port, type=int, help="Port to bind.")
    args = parser.parse_args()
    if port_is_open(args.host, args.port):
        print(
            f"Erreur: le port {args.port} est deja utilise sur {args.host}.",
            file=sys.stderr,
        )
        print(
            "Arretez l'ancien serveur (Ctrl+C dans son terminal) ou tuez le processus Python concerne.",
            file=sys.stderr,
        )
        sys.exit(1)
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
