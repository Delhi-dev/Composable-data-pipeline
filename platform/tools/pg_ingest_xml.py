from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cbcr_platform_pg.config import get_settings
from cbcr_platform_pg.database import PostgreSQLDatabase
from cbcr_platform_pg.xml_ingestion import CbcrXmlIngestor

def main() -> int:
    p=argparse.ArgumentParser(description='Ingest OECD CbC XML files from a file or directory into PostgreSQL')
    p.add_argument('location',type=Path); p.add_argument('--v2-schema',type=Path,required=True); p.add_argument('--v1-schema',type=Path)
    a=p.parse_args(); db=PostgreSQLDatabase(get_settings())
    try:
      for r in CbcrXmlIngestor(db,a.v2_schema,a.v1_schema).ingest_path(a.location): print(f'{r.status:14} {r.path} document={r.xml_document_id} {r.detail or ""}')
    finally: db.close()
    return 0
if __name__=='__main__': raise SystemExit(main())
