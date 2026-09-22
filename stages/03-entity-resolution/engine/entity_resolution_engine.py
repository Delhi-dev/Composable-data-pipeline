"""Stage 03 engine — Entity Resolution & Domestic Linkage (indicative).

Loads editable rules from ../rules, resolves thresholds from config/ (global settings),
reaches data sources through their published APIs (see config/data_source_endpoints.yaml),
evaluates the rules, and passes a result to the next stage. Stubs are marked INDICATIVE.
"""
import os, glob, yaml, sys

# make 'common' importable whether run directly or via run_pipeline.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from common.settings_loader import Settings
from common.source_client import SourceClient
from common.rule_evaluator import evaluate

STAGE = "entity-resolution"
SOURCES = ["domestic_taxpayer_registry", "transfer_pricing_return", "corporate_return"]

def load_rules():
    rules = []
    for f in sorted(glob.glob(os.path.join(_HERE, "..", "rules", "*.yaml"))):
        spec = yaml.safe_load(open(f)) or {}
        for r in spec.get("rules", []):
            r["_file"] = os.path.basename(f)
            rules.append(r)
    return rules

def run(context):
    root = context.get("root", _ROOT)
    settings = Settings(root)
    rules = load_rules()
    clients = {k: SourceClient(k, root) for k in SOURCES}
    # INDICATIVE: fetch inputs, evaluate rules against each record, collect fired rules.
    fired = []
    for key, client in clients.items():
        for rec in client.get("taxpayers"):
            for rule in rules:
                if "op" in rule and "field" in rule:
                    res = evaluate(rule, rec, settings)
                    if res and res["fired"]:
                        fired.append({"stage": STAGE, "source": key, **res})
    context.setdefault("artifacts", {})[STAGE] = {
        "rules_loaded": len(rules), "sources": SOURCES, "fired": len(fired),
    }
    print(f"[{STAGE}] rules={len(rules)} sources={SOURCES} fired={len(fired)}  -> next: 04 Data-Quality Gates")
    return context

if __name__ == "__main__":
    run({"root": _ROOT})
