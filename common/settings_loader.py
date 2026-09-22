"""Load global settings + thresholds and resolve ${settings.<dotted.path>} references."""
import os, re, yaml
_REF = re.compile(r"\$\{settings\.([a-zA-Z0-9_.]+)\}")

class Settings:
    FILES = ["config/global_settings.yaml", "config/thresholds.yaml"]
    def __init__(self, root="."):
        self.root, self.data = root, {}
        for f in self.FILES:
            p = os.path.join(root, f)
            if os.path.exists(p):
                self.data.update(yaml.safe_load(open(p)) or {})
    def get(self, dotted, default=None):
        cur = self.data
        for k in str(dotted).split("."):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur
    def resolve(self, value):
        if isinstance(value, str):
            m = _REF.fullmatch(value.strip())
            if m:
                return self.get(m.group(1))
            return _REF.sub(lambda mo: str(self.get(mo.group(1))), value)
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        return value
