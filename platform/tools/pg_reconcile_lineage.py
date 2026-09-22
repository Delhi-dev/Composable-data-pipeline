from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cbcr_platform_pg.config import get_settings  # noqa: E402
from cbcr_platform_pg.database import PostgreSQLDatabase  # noqa: E402


ZONE_TABLE = {
    "canonical": "cbcr_canonical.report",
    "dq_passed": "cbcr_dq_published.report",
    "enriched": "cbcr_enriched.report",
    "risk_ready": "cbcr_risk_ready.report",
}
TRANSITIONS = {
    ("landing", "canonical"),
    ("canonical", "dq_passed"),
    ("canonical", "enriched"),
    ("dq_passed", "enriched"),
    ("dq_passed", "risk_ready"),
    ("enriched", "risk_ready"),
}


def main() -> int:
    database = PostgreSQLDatabase(get_settings())
    defects: list[str] = []
    try:
        datasets = database.all("SELECT dataset_id,version,zone,report_count FROM cbcr_control.dataset")
        for dataset in datasets:
            table = ZONE_TABLE.get(dataset["zone"])
            if not table:
                continue
            actual = database.one(
                f"SELECT count(*)::int AS count FROM {table} WHERE dataset_id=%s AND dataset_version=%s",
                (dataset["dataset_id"], dataset["version"]),
            )["count"]
            if actual != dataset["report_count"]:
                defects.append(
                    f"count mismatch {dataset['dataset_id']}/v{dataset['version']}: registered={dataset['report_count']} actual={actual}"
                )
        edges = database.all(
            """SELECT p.zone AS parent_zone,c.zone AS child_zone,l.parent_dataset_id,l.child_dataset_id
               FROM cbcr_control.dataset_lineage l
               JOIN cbcr_control.dataset p ON p.dataset_id=l.parent_dataset_id AND p.version=l.parent_version
               JOIN cbcr_control.dataset c ON c.dataset_id=l.child_dataset_id AND c.version=l.child_version"""
        )
        for edge in edges:
            if (edge["parent_zone"], edge["child_zone"]) not in TRANSITIONS:
                defects.append(
                    f"invalid transition {edge['parent_zone']}->{edge['child_zone']} "
                    f"({edge['parent_dataset_id']}->{edge['child_dataset_id']})"
                )
        cycles = database.one(
            """WITH RECURSIVE walk(root,node,path,cycle) AS (
                   SELECT parent_dataset_id,child_dataset_id,
                          ARRAY[parent_dataset_id,child_dataset_id],false
                   FROM cbcr_control.dataset_lineage
                   UNION ALL
                   SELECT w.root,l.child_dataset_id,w.path||l.child_dataset_id,
                          l.child_dataset_id=ANY(w.path)
                   FROM walk w JOIN cbcr_control.dataset_lineage l ON l.parent_dataset_id=w.node
                   WHERE NOT w.cycle
               ) SELECT count(*)::int AS count FROM walk WHERE cycle"""
        )["count"]
        if cycles:
            defects.append(f"lineage cycles={cycles}")
        orphan_count = database.one(
            """SELECT count(*)::int AS count FROM cbcr_control.dataset d
               WHERE d.zone<>'landing' AND NOT EXISTS(
                   SELECT 1 FROM cbcr_control.dataset_lineage l
                   WHERE l.child_dataset_id=d.dataset_id AND l.child_version=d.version)"""
        )["count"]
        if orphan_count:
            defects.append(f"non-landing datasets without parent={orphan_count}")
        if defects:
            for defect in defects:
                print(f"FAIL {defect}")
            return 1
        print(f"PASS datasets={len(datasets)} lineage_edges={len(edges)} defects=0")
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
