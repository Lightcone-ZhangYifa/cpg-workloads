"""Read original CPG definitions and local observations; never install a tool."""
from pathlib import Path
import argparse
import hashlib
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--prefix-root", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    args = parser.parse_args()
    import compiler_playground
    from compiler_playground.packages import PackageManager
    if compiler_playground.__version__ != "0.21.14":
        raise SystemExit("This reuse audit binds CPG 0.21.14; review definitions before using another version.")
    if args.output.exists():
        raise SystemExit("Use a new audit output file.")
    root = Path(__file__).resolve().parent
    identities = json.loads((root / "original-identities.json").read_text())
    manager = PackageManager(state=args.state, prefix_root=args.prefix_root, cache=args.cache)
    results = []
    for original in identities:
        resource = original["resource_id"]
        detail = manager.info(resource)
        definition = detail["definition"]
        saved = json.loads((root / "original-definitions" / resource / "package.json").read_text())
        if definition != saved:
            raise SystemExit("Original resource definition differs: " + resource)
        if definition["metadata"]["catalog_sha256"] != original["original_catalog_sha256"]:
            raise SystemExit("Original catalog digest differs: " + resource)
        results.append({"id": resource, "info": detail, "paths": manager.paths(resource, files=True),
                        "catalog_sha256_matches": True, "complete_definition_matches": True})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"api": "compiler_playground.packages.PackageManager.info/paths",
        "baseline_version": compiler_playground.__version__, "registry_sha256": manager.registry.sha256,
        "operations_mutating_resources": 0, "results": results}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed", "definitions": len(results), "mutations": 0,
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
