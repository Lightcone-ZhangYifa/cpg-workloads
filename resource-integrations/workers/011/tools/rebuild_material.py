#!/usr/bin/env python3
"""Rebuild the pinned worker 011 material package from its local source master."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from build_payload import run as build_payload
from compiler_playground.packages import pack, verify_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Use a new output archive: " + str(output))
    spec = json.loads((bundle / "cpg/package.json").read_text(encoding="utf-8"))
    if spec["id"] != "reference-pack.worker-011":
        raise ValueError("This builder belongs to reference-pack.worker-011")
    index = json.loads((bundle / "cpg/package-index.json").read_text(encoding="utf-8"))
    matches = [item for item in index["artifacts"]
               if all(item.get(key) == spec[key] for key in ("id", "version", "build"))]
    if len(matches) != 1 or matches[0]["method"] != "material":
        raise ValueError("The current package identity needs one material artifact lock")
    expected = matches[0]
    provenance = json.loads((bundle / "cpg/packaging-provenance.json").read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".worker011-rebuild-", dir=output.parent) as temporary:
        payload = Path(temporary) / "payload"
        built = build_payload(bundle, payload)
        pack(spec, output, method="material", payload=payload,
             recipe_dir=bundle / "cpg/recipe", relocatable=True, provenance=provenance)
    verified = verify_package(output, expected_sha256=expected["sha256"],
                              expected_bytes=expected["bytes"])
    if verified["manifest"]["manifest_sha256"] != expected["manifest_sha256"]:
        raise ValueError("The rebuilt manifest differs from the pinned artifact")
    print(json.dumps({"status": "passed", "id": spec["id"], "version": spec["version"],
                      "build": spec["build"], "method": "material",
                      "sha256": verified["sha256"], "bytes": verified["bytes"],
                      "manifest_sha256": verified["manifest"]["manifest_sha256"],
                      "payload_files": built["payload_files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
