"""Debt-shifting / thin capitalisation typology plugin (indicative)."""

ID = "debt_shifting"
VERSION = 1

def required_cbcr_indicators():
    return ["MX-001", "MX-002"]

def required_local_indicators():
    return ["interest_out_to_risk_juris", "thin_cap_ratio", "interest_ebitda_breach", "wht_treaty_strip"]

def evaluate(entity, cbcr_flags, local_indicators, settings):
    """Gate: a CbCR flag on jurisdiction J must co-occur with a domestic indicator on J.
    Returns an indicative correlation score in [0,1] or None."""
    weights = settings.get("scoring_weights.debt_shifting", {}) or {}
    flagged_juris = {f.get("implicated_juris") for f in cbcr_flags
                     if f.get("macro_indicator") in required_cbcr_indicators()}
    contributing, score = [], 0.0
    for ind in local_indicators:
        if ind.get("indicator_id") in required_local_indicators() \
           and ind.get("jurisdiction") in flagged_juris:
            w = weights.get(ind["indicator_id"], 0.0)
            score += w * float(ind.get("severity", 0.0))
            contributing.append(ind)
    if not contributing:
        return None
    return {"use_case_id": ID, "entity_key": entity.get("entity_key"),
            "correlation_score": round(min(score, 1.0), 4),
            "implicated_juris": sorted(flagged_juris)[0] if flagged_juris else None,
            "contributing": contributing}

def reason_codes(result, settings):
    return [{"code": "RC-DEBT-001", "use_case_id": ID,
             "implicated_juris": result.get("implicated_juris")}]
