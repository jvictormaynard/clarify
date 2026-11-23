"""Explicit operator entry point; there is no default deployment or secret."""

import argparse
from pathlib import Path
from .account import AccountValidator
from .control import Control
from .server import signaling_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-origin", required=True)
    parser.add_argument("--turn-secret-file", required=True)
    parser.add_argument("--turn-url", action="append", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    secret = Path(args.turn_secret_file).read_bytes().strip()
    control = Control(
        AccountValidator(args.account_origin),
        turn_secret=secret,
        turn_urls=args.turn_url,
        database=args.database,
    )
    server = signaling_server(("127.0.0.1", args.port), control)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
