from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cbcr_platform_pg.container import PostgreSQLContainer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read PostgreSQL function queue diagnostics")
    parser.add_argument("--recover-expired", action="store_true")
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    container = PostgreSQLContainer()
    try:
        if args.recover_expired:
            if args.confirm_database != container.settings.database:
                raise SystemExit("--confirm-database must match target for recovery")
            recovered = container.runs.recover_expired()
            print(f"recovered={recovered}")
        rows = container.db.all(
            """SELECT status,count(*)::int AS count,min(queued_at) AS oldest,
                      count(*) FILTER(WHERE status='running' AND lease_expires_at<clock_timestamp())::int AS expired
               FROM cbcr_control.function_run GROUP BY status ORDER BY status"""
        )
        for row in rows:
            print(
                f"status={row['status']} count={row['count']} expired={row['expired']} "
                f"oldest={row['oldest']}"
            )
        return 0
    finally:
        container.close()


if __name__ == "__main__":
    raise SystemExit(main())
