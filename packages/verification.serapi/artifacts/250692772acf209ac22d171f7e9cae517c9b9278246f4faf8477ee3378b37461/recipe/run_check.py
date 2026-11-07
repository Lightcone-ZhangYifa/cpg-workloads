#!/usr/bin/env python3
"""Give each real proof checker a fresh output directory and preserve its exit."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise SystemExit("A real checker command is required")
    args.output_root.mkdir(parents=True, exist_ok=True)
    # The child requires a nonexistent leaf. The unique parent is allocated
    # atomically, without changing its proof or its success/failure semantics.
    parent = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_root))
    output = parent / "evidence"
    result = subprocess.run(command + ["--output", str(output)], check=False)
    receipt = {"status": "passed" if result.returncode == 0 else "failed",
               "checker_exit": result.returncode, "command": command, "output": str(output)}
    (parent / "invocation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
