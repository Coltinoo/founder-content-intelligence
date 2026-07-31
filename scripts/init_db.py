#!/usr/bin/env python
"""Create (or reset) the database schema.

Usage:
    python scripts/init_db.py            # create missing tables, idempotent
    python scripts/init_db.py --reset    # DROP everything and recreate
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

from fcie.db import describe_backend, init_db, reset_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialise the FCIE database.")
    parser.add_argument("--reset", action="store_true",
                        help="Drop every table first. Destructive.")
    args = parser.parse_args()

    print(f"Database backend: {describe_backend()}")

    if args.reset:
        confirm = input("This will DELETE all stored data. Type 'reset' to continue: ")
        if confirm.strip().lower() != "reset":
            print("Aborted.")
            return 1
        reset_db()
        print("Schema dropped and recreated.")

    tables = init_db()
    print(f"{len(tables)} table(s) present:")
    for table in tables:
        print(f"  · {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
