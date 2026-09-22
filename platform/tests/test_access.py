from __future__ import annotations

from cbcr_platform.access import AccessDenied


def test_one_user_can_derive_permissions_from_many_roles(services):
    _, access, _ = services
    assert access.decide("demo", "run_function", stage="04", purpose="data_quality").allowed
    assert access.decide("demo", "run_function", stage="05", purpose="risk_assessment").allowed
    assert access.decide("demo", "run_function", stage="07", purpose="case_review").allowed


def test_purpose_and_stage_are_part_of_authorisation(services):
    _, access, _ = services
    assert not access.decide("auditor", "run_function", stage="04", purpose="data_quality").allowed
    try:
        access.require("demo", "run_function", stage="06", purpose="case_review")
    except AccessDenied:
        pass
    else:
        raise AssertionError("case purpose must not grant Stage 06 execution")


def test_explicit_deny_wins_over_union_of_grants(services):
    db, access, _ = services
    db.execute("INSERT INTO role_permissions(role_id,action,stage,purpose,effect) VALUES(?,?,?,?,?)",
               ("platform_admin", "run_function", "05", "risk_assessment", "deny"))
    decision = access.decide("demo", "run_function", stage="05", purpose="risk_assessment")
    assert not decision.allowed
    assert decision.reason == "explicit deny"
