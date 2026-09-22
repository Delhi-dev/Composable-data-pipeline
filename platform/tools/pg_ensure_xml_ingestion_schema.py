"""Create/update and verify the database objects needed by CbC XML ingestion."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2

from pg_apply_migrations import main as apply_migrations

REQUIRED = {
    "cbcr_staging.xml_document", "cbcr_staging.xml_validation_issue", "cbcr_staging.xml_ingestion_attempt",
    "public.cbcr_message_spec", "public.cbcr_body", "public.cbcr_reporting_entity",
    "public.cbcr_cbcreport", "public.cbcr_cbcreport_summary", "public.cbcr_const_entity",
    "public.cbcr_const_entity_business_activity", "public.cbcr_additional_info",
    "public.cbcr_additional_info_text", "public.cbcr_document_correction_ref",
}

def main() -> int:
    p=argparse.ArgumentParser(description="Ensure CbC XML ingestion PostgreSQL schemas/tables are installed")
    p.add_argument("--host",default=os.getenv("CBCR_PG_HOST","localhost")); p.add_argument("--port",default=os.getenv("CBCR_PG_PORT","5432"),type=int)
    p.add_argument("--database",default=os.getenv("CBCR_PG_DATABASE","cbcr")); p.add_argument("--user",default=os.getenv("CBCR_PG_MIGRATION_USER","postgres"))
    p.add_argument("--password-env",default=os.getenv("CBCR_PG_MIGRATION_PASSWORD_ENV","CBCR_PG_MIGRATION_PASSWORD")); p.add_argument("--confirm-database",required=True)
    a=p.parse_args()
    if a.confirm_database != a.database: raise SystemExit("--confirm-database must exactly match --database")
    if not os.getenv(a.password_env): raise SystemExit(f"Set {a.password_env}; passwords are not accepted on the command line")
    old=list(sys.argv); sys.argv=["pg_apply_migrations.py","--host",a.host,"--port",str(a.port),"--database",a.database,"--user",a.user,"--password-env",a.password_env,"--through","009","--confirm-database",a.database]
    try: apply_migrations()
    finally: sys.argv=old
    conn=psycopg2.connect(host=a.host,port=a.port,dbname=a.database,user=a.user,password=os.getenv(a.password_env))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT table_schema||'.'||table_name FROM information_schema.tables WHERE (table_schema='public' OR table_schema='cbcr_staging') AND table_type='BASE TABLE'")
            missing=REQUIRED-{row[0] for row in cur.fetchall()}
            cur.execute("SELECT migration_id FROM cbcr_control.schema_migration WHERE migration_id='009_xml_ingestion_runtime'")
            if missing or not cur.fetchone(): raise RuntimeError(f"XML ingestion schema incomplete; missing: {', '.join(sorted(missing))}")
        print(f"PASS XML ingestion schema is ready in database={a.database}; tables={len(REQUIRED)} migration=009")
    finally: conn.close()
    return 0

if __name__=='__main__': raise SystemExit(main())
