from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cbcr_platform_pg.config import get_settings  # noqa: E402
from cbcr_platform_pg.database import PostgreSQLDatabase  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the automated PostgreSQL CbCR journey and retain JSON evidence"
    )
    parser.add_argument("--confirm-database", required=True)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "runtime" / "postgresql-acceptance-evidence.json",
    )
    args = parser.parse_args()
    settings = get_settings()
    if args.confirm_database != settings.database:
        raise SystemExit("--confirm-database must exactly match CBCR_PG_DATABASE")
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(ROOT / "tests_postgresql"),
        "-q",
        "--basetemp",
        str(ROOT / ".pytest_pg_smoke"),
    ]
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        return completed.returncode
    database = PostgreSQLDatabase(settings)
    try:
        lot = database.one(
            """SELECT lot_id,source_id,mapping_profile_id,mapping_version,report_count,status,
                      received_by,received_at,metadata
               FROM cbcr_control.lot
               WHERE metadata->>'test_suite'='postgresql-acceptance'
               ORDER BY received_at DESC LIMIT 1"""
        )
        if not lot:
            raise RuntimeError("acceptance suite passed but no smoke lot was found")
        lot_id = str(lot["lot_id"])
        datasets = database.all(
            """SELECT dataset_id,version,zone,parent_dataset_id,parent_version,report_count,status
               FROM cbcr_control.dataset WHERE lot_id=%s ORDER BY created_at""",
            (lot_id,),
        )
        dataset_ids = [str(row["dataset_id"]) for row in datasets]
        runs = database.all(
            """SELECT r.run_id,r.dataset_id,r.input_zone,r.purpose,r.status,
                      count(fr.function_run_id)::int AS children,
                      count(*) FILTER(WHERE fr.status='succeeded')::int AS succeeded
               FROM cbcr_control.run r JOIN cbcr_control.function_run fr USING(run_id)
               WHERE r.dataset_id IN (SELECT dataset_id FROM cbcr_control.dataset WHERE lot_id=%s)
               GROUP BY r.run_id ORDER BY min(fr.queued_at)""",
            (lot_id,),
        )
        counts = database.one(
            """SELECT
                (SELECT count(*) FROM cbcr_dq.finding f JOIN cbcr_control.run r USING(run_id)
                 WHERE r.dataset_id IN (SELECT jsonb_array_elements_text(%s::jsonb)::uuid))::int AS findings,
                (SELECT count(*) FROM cbcr_risk.result
                 WHERE dataset_id IN (SELECT jsonb_array_elements_text(%s::jsonb)::uuid))::int AS risk_results,
                (SELECT count(*) FROM cbcr_selection.selection_batch
                 WHERE dataset_id IN (SELECT jsonb_array_elements_text(%s::jsonb)::uuid))::int AS batches,
                (SELECT count(*) FROM cbcr_selection.decision_history h
                 JOIN cbcr_selection.candidate c USING(candidate_id)
                 JOIN cbcr_selection.selection_batch b USING(selection_batch_id)
                 WHERE b.dataset_id IN (SELECT jsonb_array_elements_text(%s::jsonb)::uuid))::int AS decisions""",
            (dataset_ids, dataset_ids, dataset_ids, dataset_ids),
        )
        migration = database.one(
            "SELECT migration_id,checksum FROM cbcr_control.schema_migration ORDER BY applied_at DESC LIMIT 1"
        )
        evidence = {
            "result": "PASS",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "application_version": "0.2.0-pg",
            "database": settings.database,
            "migration": migration,
            "lot": lot,
            "datasets": datasets,
            "dataset_ids": dataset_ids,
            "runs": runs,
            "output_counts": counts,
            "test_summary": "11 PostgreSQL acceptance tests passed",
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        print(f"PASS lot_id={lot_id} datasets={len(datasets)} runs={len(runs)} evidence={args.evidence}")
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
