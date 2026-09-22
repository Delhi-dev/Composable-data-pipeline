"""Evaluate a simple rule spec {field, op, threshold} against a record.
Thresholds may be ${settings...} references, resolved via the Settings instance."""
OPS = {
  "gt": lambda a,b: a > b, "gte": lambda a,b: a >= b,
  "lt": lambda a,b: a < b, "lte": lambda a,b: a <= b,
  "eq": lambda a,b: a == b, "ne": lambda a,b: a != b,
  "in": lambda a,b: a in (b or []), "not_in": lambda a,b: a not in (b or []),
  "missing": lambda a,b: a in (None, ""), "present": lambda a,b: a not in (None, ""),
}
def evaluate(rule, record, settings):
    field, op = rule.get("field"), rule.get("op")
    if op not in OPS:
        return None
    thr = settings.resolve(rule.get("threshold")) if "threshold" in rule else None
    try:
        thr = float(thr)
    except (TypeError, ValueError):
        pass
    val = record.get(field) if field else None
    try:
        fired = OPS[op](val, thr)
    except Exception:
        fired = False
    return {"rule_id": rule.get("id"), "fired": bool(fired), "field": field,
            "op": op, "value": val, "threshold": thr, "severity": rule.get("severity"),
            "action": rule.get("action")}
