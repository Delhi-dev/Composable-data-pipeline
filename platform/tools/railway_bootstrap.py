"""Prepare a Railway PostgreSQL service for the CbCR app. Safe to run on every deploy.

1. Creates the `cbcr` database and the `cbcr_user` login role if they are missing
   (and keeps the role's password in sync with CBCR_SOURCE_DB_PASSWORD).
2. Creates the migration ledger table early (the repo's tool needs it before 001 runs),
   then applies migrations 000-009 with the repo's own tool (applied ones are skipped).
3. Applies 010_xml_payload_trigger_fix, which the migration tool does not cover.
   It is a CREATE OR REPLACE FUNCTION, so repeating it is harmless.

Run as a Railway pre-deploy command:  python platform/tools/railway_bootstrap.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv("CBCR_PG_DATABASE", "cbcr")
APP_USER = os.getenv("CBCR_PG_USER", "cbcr_user")


def connect(dbname: str):
    return psycopg2.connect(
        host=os.environ["CBCR_PG_HOST"],
        port=int(os.getenv("CBCR_PG_PORT", "5432")),
        user=os.getenv("CBCR_PG_MIGRATION_USER", "postgres"),
        password=os.environ["CBCR_PG_MIGRATION_PASSWORD"],
        dbname=dbname,
        connect_timeout=10,
    )


def ensure_database_and_role() -> None:
    app_password = os.environ[os.getenv("CBCR_PG_PASSWORD_ENV", "CBCR_SOURCE_DB_PASSWORD")]
    conn = connect(os.getenv("CBCR_PG_ADMIN_DATABASE", "postgres"))
    conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{DATABASE}"')
                print(f"Created database {DATABASE}")
            else:
                print(f"Database {DATABASE} already exists")
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE ROLE "{APP_USER}" LOGIN PASSWORD %s', (app_password,))
                print(f"Created role {APP_USER}")
            else:
                cur.execute(f'ALTER ROLE "{APP_USER}" LOGIN PASSWORD %s', (app_password,))
                print(f"Role {APP_USER} already exists; password refreshed")
    finally:
        conn.close()


def ensure_migration_ledger() -> None:
    """pg_apply_migrations.py records 000 before 001 has created its ledger table, so on a
    fresh database it crashes. Create the ledger up front, exactly as 001 defines it."""
    conn = connect(DATABASE)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE SCHEMA IF NOT EXISTS cbcr_control;
                   CREATE TABLE IF NOT EXISTS cbcr_control.schema_migration (
                     migration_id varchar(100) PRIMARY KEY,
                     description text NOT NULL,
                     applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                   );"""
            )
    finally:
        conn.close()


def apply_migrations() -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "pg_apply_migrations.py"),
            "--database", DATABASE,
            "--confirm-database", DATABASE,
        ],
        check=True,
    )


def apply_trigger_fix() -> None:
    path = ROOT / "migrations" / "postgresql" / "010_xml_payload_trigger_fix.sql"
    sql = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("\\")
    )
    conn = connect(DATABASE)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print(f"APPLY {path.name}")
    finally:
        conn.close()


def main() -> int:
    if DATABASE != "cbcr" or APP_USER != "cbcr_user":
        raise SystemExit("The migrations hard-code database 'cbcr' and role 'cbcr_user'; keep those names.")
    ensure_database_and_role()
    ensure_migration_ledger()
    apply_migrations()
    apply_trigger_fix()
    print("Railway database setup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
