from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = ROOT / "migrations" / "postgresql"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Apply pending CbCR PostgreSQL migrations")
    value.add_argument("--host", default=os.getenv("CBCR_PG_HOST", "localhost"))
    value.add_argument("--port", type=int, default=int(os.getenv("CBCR_PG_PORT", "5432")))
    value.add_argument("--database", default=os.getenv("CBCR_PG_DATABASE", "cbcr"))
    value.add_argument("--user", default=os.getenv("CBCR_PG_MIGRATION_USER", "postgres"))
    value.add_argument(
        "--password-env", default=os.getenv("CBCR_PG_MIGRATION_PASSWORD_ENV", "CBCR_PG_MIGRATION_PASSWORD")
    )
    value.add_argument(
        "--through",
        choices=["000", "001", "002", "003", "004", "005", "006", "007", "008", "009"],
        default="009",
    )
    value.add_argument(
        "--confirm-database",
        required=True,
        help="Must exactly match --database; prevents accidental migration of another database",
    )
    return value


def has_checksum_column(connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS(
                   SELECT 1 FROM information_schema.columns
                   WHERE table_schema='cbcr_control' AND table_name='schema_migration'
                     AND column_name='checksum')"""
        )
        return bool(cursor.fetchone()[0])


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def applied(connection, migration_id: str, expected_checksum: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('cbcr_control.schema_migration')")
        if cursor.fetchone()[0] is None:
            return False
        if has_checksum_column(connection):
            cursor.execute(
                "SELECT checksum FROM cbcr_control.schema_migration WHERE migration_id=%s",
                (migration_id,),
            )
            row = cursor.fetchone()
            if row and row[0] and row[0] != expected_checksum:
                raise RuntimeError(f"migration checksum conflict: {migration_id}")
            return row is not None
        cursor.execute(
            "SELECT 1 FROM cbcr_control.schema_migration WHERE migration_id=%s",
            (migration_id,),
        )
        return cursor.fetchone() is not None


def migration_sql(path: Path) -> str:
    """Return driver-compatible SQL, omitting psql-only meta commands."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("\\")
    )


def record(connection, migration_id: str, value_checksum: str) -> None:
    with connection.cursor() as cursor:
        if has_checksum_column(connection):
            cursor.execute(
                """INSERT INTO cbcr_control.schema_migration(migration_id,description,checksum)
                   VALUES(%s,%s,%s)
                   ON CONFLICT(migration_id) DO UPDATE
                   SET checksum=COALESCE(cbcr_control.schema_migration.checksum,excluded.checksum)""",
                (migration_id, f"Applied from {migration_id}.sql", value_checksum),
            )
        else:
            cursor.execute(
                """INSERT INTO cbcr_control.schema_migration(migration_id,description)
                   VALUES(%s,%s) ON CONFLICT(migration_id) DO NOTHING""",
                (migration_id, f"Applied from {migration_id}.sql"),
            )


def main() -> int:
    args = parser().parse_args()
    password = os.getenv(args.password_env)
    if not password:
        raise SystemExit(f"Set {args.password_env}; passwords are not accepted on the command line")
    if args.confirm_database != args.database:
        raise SystemExit("--confirm-database must exactly match --database")
    connection = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.database, user=args.user, password=password
    )
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext('cbcr_pipeline_migrations'))")
        connection.commit()
        for path in sorted(MIGRATION_ROOT.glob("*.sql")):
            sequence = path.name[:3]
            if sequence > args.through:
                continue
            migration_id = path.stem
            value_checksum = checksum(path)
            if applied(connection, migration_id, value_checksum):
                print(f"SKIP {path.name} (already applied)")
                continue
            try:
                with connection.cursor() as cursor:
                    cursor.execute(migration_sql(path))
                record(connection, migration_id, value_checksum)
                connection.commit()
                print(f"APPLY {path.name}")
            except Exception:
                connection.rollback()
                raise
        # Migration 005 introduces checksums. Backfill earlier immutable files once,
        # then all subsequent executions enforce conflict detection.
        if has_checksum_column(connection):
            for path in sorted(MIGRATION_ROOT.glob("*.sql")):
                if path.name[:3] <= args.through and applied(connection, path.stem, checksum(path)):
                    record(connection, path.stem, checksum(path))
            connection.commit()
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext('cbcr_pipeline_migrations'))")
            connection.commit()
        except Exception:
            connection.rollback()
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
