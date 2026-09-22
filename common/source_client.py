"""Generic data-source client. In production this calls the source's published API
(base_url + OpenAPI in config/data_source_endpoints.yaml). Here it reads mock_data/ if present."""
import os, json, yaml

class SourceClient:
    def __init__(self, source_key, root="."):
        self.key, self.root = source_key, root
        cfg = {}
        p = os.path.join(root, "config/data_source_endpoints.yaml")
        if os.path.exists(p):
            cfg = yaml.safe_load(open(p)) or {}
        self.meta = (cfg.get("sources", {}) or {}).get(source_key, {})
    def get(self, resource, **params):
        # INDICATIVE stub — real impl issues an HTTP call to self.meta['base_url'].
        p = os.path.join(self.root, "mock_data", f"{self.key}.json")
        if os.path.exists(p):
            data = json.load(open(p))
            if isinstance(data, dict):
                return data.get(resource, [])
            return data
        return []
    def post(self, resource, payload):
        print(f"  (indicative) POST {self.meta.get('base_url','')}/{resource}: "
              f"{payload.get('entity_key','?')}")
        return {"status": "accepted"}
