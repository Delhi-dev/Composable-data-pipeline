from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cbcr_platform.bootstrap import FUNCTIONS  # noqa: E402
from cbcr_platform_pg.bootstrap import seed  # noqa: E402
from cbcr_platform_pg.config import get_settings  # noqa: E402
from cbcr_platform_pg.database import PostgreSQLDatabase  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or idempotently seed PostgreSQL catalogue")
    parser.add_argument("--apply", action="store_true", help="Apply missing seed rows")
    parser.add_argument("--confirm-database", help="Required with --apply and must match target")
    args = parser.parse_args()
    settings = get_settings()
    if args.apply and args.confirm_database != settings.database:
        raise SystemExit("--confirm-database must match CBCR_PG_DATABASE when --apply is used")
    database = PostgreSQLDatabase(settings)
    try:
        before = database.one(
            """SELECT
                 (SELECT count(*) FROM cbcr_control.source)::int AS sources,
                 (SELECT count(*) FROM cbcr_control.pipeline_profile)::int AS profiles,
                 (SELECT count(*) FROM cbcr_control.role)::int AS roles,
                 (SELECT count(*) FROM cbcr_control.user_account)::int AS users,
                 (SELECT count(*) FROM cbcr_control.function_definition WHERE lifecycle='active')::int AS functions"""
        )
        if args.apply:
            seed(database)
        after = database.one(
            """SELECT
                 (SELECT count(*) FROM cbcr_control.source)::int AS sources,
                 (SELECT count(*) FROM cbcr_control.pipeline_profile)::int AS profiles,
                 (SELECT count(*) FROM cbcr_control.role)::int AS roles,
                 (SELECT count(*) FROM cbcr_control.user_account)::int AS users,
                 (SELECT count(*) FROM cbcr_control.function_definition WHERE lifecycle='active')::int AS functions"""
        )
        missing_functions = max(0, len(FUNCTIONS) - after["functions"])
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode} database={settings.database} before={before} after={after} missing_functions={missing_functions}")
        return 1 if missing_functions else 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
