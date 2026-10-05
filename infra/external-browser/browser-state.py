#!/usr/bin/env python3
"""Encrypt and decrypt Thorio's persistent Playwright storage state.

The encrypted file is safe to keep in GitHub Actions artifacts. The plaintext
state contains authenticated browser cookies and must never be uploaded.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def _key() -> bytes:
    value = os.environ.get("THORIO_BROWSER_STATE_ENCRYPTION_KEY", "").strip()
    if not value:
        raise SystemExit(
            "THORIO_BROWSER_STATE_ENCRYPTION_KEY is required. "
            "Create a dedicated GitHub Actions secret containing a Fernet key."
        )
    try:
        Fernet(value.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SystemExit(
            "THORIO_BROWSER_STATE_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc
    return value.encode("ascii")


def encrypt(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Browser state file does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = Fernet(_key()).encrypt(source.read_bytes())
    destination.write_bytes(token)
    source.unlink()


def decrypt(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Encrypted browser state does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        plaintext = Fernet(_key()).decrypt(source.read_bytes())
    except InvalidToken as exc:
        raise SystemExit(
            "Encrypted browser state could not be decrypted with the configured key."
        ) from exc
    destination.write_bytes(plaintext)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("encrypt", "decrypt"):
        item = sub.add_parser(command)
        item.add_argument("source", type=Path)
        item.add_argument("destination", type=Path)

    args = parser.parse_args()
    if args.command == "encrypt":
        encrypt(args.source, args.destination)
    else:
        decrypt(args.source, args.destination)


if __name__ == "__main__":
    main()
