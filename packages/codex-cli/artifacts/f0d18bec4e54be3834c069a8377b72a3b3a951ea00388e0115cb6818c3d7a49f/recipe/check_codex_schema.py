"""Exercise Codex's offline protocol-schema export; never request model service."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def invoke(executable, output, work, timeout):
    # This dispatch branch writes bundled schemas and does not start an agent.
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "TMPDIR": str(work)}
    return subprocess.run(
        [str(executable), "app-server", "generate-json-schema", "--out", str(output)],
        cwd=work, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    executable = args.prefix.resolve() / "vendor/x86_64-unknown-linux-musl/bin/codex"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("The delivered Codex native bundle executable is unavailable")
    args.build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cpg-codex-schema-", dir=args.build) as name:
        work = Path(name).resolve()
        output = work / "schemas"
        result = invoke(executable, output, work, 45)
        if result.returncode:
            raise RuntimeError("Offline schema export failed: " + result.stderr.decode("utf-8", "replace")[-2000:])
        paths = sorted(output.rglob("*.json"))
        if not paths or len(paths) > 2000:
            raise RuntimeError("Unexpected schema export file count")
        total = 0
        documents = {}
        for path in paths:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(output.resolve()):
                raise RuntimeError("Schema export contains an unexpected path")
            total += path.stat().st_size
            if total > 64 * 1024 * 1024:
                raise RuntimeError("Schema export exceeds the bounded check size")
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise RuntimeError("A generated schema is not a JSON object")
            documents[path.relative_to(output).as_posix()] = document
        request = documents.get("ClientRequest.json")
        if not request or request.get("title") != "ClientRequest" or "json-schema.org" not in request.get("$schema", ""):
            raise RuntimeError("Generated ClientRequest schema contract is missing")
        alternatives = request.get("oneOf", [])
        methods = set()
        for branch in alternatives:
            properties = branch.get("properties", {})
            methods.update(properties.get("method", {}).get("enum", []))
        if not {"initialize", "thread/start", "turn/start"}.issubset(methods):
            raise RuntimeError("Generated schema omits required request methods")
        # Resolve references against the actual generated document, not a golden log.
        references = 0
        def visit(value):
            nonlocal references
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/"):
                    cursor = request
                    for segment in ref[2:].split("/"):
                        cursor = cursor[segment.replace("~1", "/").replace("~0", "~")]
                    references += 1
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(request)
        if references < 1:
            raise RuntimeError("Generated request schema has no resolvable type references")
        # Exercise a real failure path: the requested output directory is a file.
        blocked = work / "occupied-output"
        blocked.write_text("occupied\n", encoding="utf-8")
        rejected = invoke(executable, blocked, work, 15)
        if rejected.returncode == 0 or blocked.read_text(encoding="utf-8") != "occupied\n":
            raise RuntimeError("Schema exporter did not reject an invalid output directory")
        print(json.dumps({"status": "passed", "scope": "offline_protocol_schema_export", "schemas": len(paths), "request_methods": len(methods), "resolved_local_references": references}))


if __name__ == "__main__":
    main()
