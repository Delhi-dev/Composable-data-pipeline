#!/usr/bin/env python3
"""Indicative end-to-end run: loads each stage engine in order and passes a shared
context through. Uses mock_data/ so it runs without live source systems.
    python3 run_pipeline.py
"""
import importlib.util, os, glob, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

def load(path):
    name = "eng_" + os.path.basename(os.path.dirname(os.path.dirname(path))) .replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def main():
    os.chdir(ROOT)
    ctx = {"root": ROOT, "artifacts": {}}
    engines = sorted(glob.glob("stages/*/engine/*_engine.py"))
    print("CbCR pipeline — indicative run\n" + "=" * 40)
    for ef in engines:
        mod = load(ef)
        if hasattr(mod, "run"):
            ctx = mod.run(ctx)
    print("=" * 40)
    print("Stages executed:", list(ctx["artifacts"].keys()))

if __name__ == "__main__":
    main()
