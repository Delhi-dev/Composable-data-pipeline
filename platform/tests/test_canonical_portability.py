from __future__ import annotations

import json

from cbcr_platform.canonical import CanonicalMapper, FixtureSourceAdapter
from cbcr_platform.config import get_settings


def test_two_physical_schemas_produce_the_same_canonical_contract(services):
    db, _, _ = services
    fixture = FixtureSourceAdapter(get_settings(db.path).fixture_root)
    mapped = []
    for source_id in ("fixture_alpha", "fixture_beta"):
        source = db.one("SELECT * FROM sources WHERE source_id=?", (source_id,))
        profile = db.one("SELECT * FROM mapping_profiles WHERE source_id=? AND lifecycle='active'", (source_id,))
        mapper = CanonicalMapper(json.loads(profile["mapping_json"]))
        mapped.append(mapper.map_report(fixture.records(source["endpoint_link"])[0]))
    assert mapped[0] == mapped[1]
    assert mapped[0].report_id == "RPT-2025-001"
    assert mapped[0].metrics[1].profit_before_tax == 30_000_000


def test_rule_library_contains_two_active_functions_per_stage(services):
    db, _, _ = services
    rows = db.all("SELECT stage,COUNT(*) AS n FROM function_definitions WHERE lifecycle='active' GROUP BY stage")
    assert {row["stage"]: row["n"] for row in rows} == {f"0{i}": 2 for i in range(1, 8)}


def test_seeded_mappings_cover_stable_required_contract(services):
    db, _, _ = services
    from cbcr_platform.catalog import CatalogueService
    catalogue = CatalogueService(db)
    assert catalogue.mapping_validation("alpha_v1", 1)["valid"]
    assert catalogue.mapping_validation("beta_v1", 1)["valid"]
