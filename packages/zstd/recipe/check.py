"""Validate a selected native-format Zstandard installation and its own library."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(prefix: Path, *, version_only=False):
    prefix = prefix.resolve(strict=True)
    env = dict(os.environ, LC_ALL="C")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "ZSTD_CLEVEL", "ZSTD_NBTHREADS"):
        env.pop(key, None)
    commands = []

    def run(argv, *, cwd=None, expected=0):
        argv = [str(item) for item in argv]
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
        row = {"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        commands.append(row)
        if (expected == 0 and result.returncode != 0) or (expected == "nonzero" and result.returncode == 0):
            raise RuntimeError(json.dumps(row))
        return result.stdout + result.stderr

    cli = prefix / "bin/zstd"
    version = run([cli, "--version"])
    if "v1.5.7" not in version:
        raise RuntimeError("The selected CLI is not Zstandard v1.5.7: " + version)
    if version_only:
        return {"status": "passed", "kind": "version", "version": "1.5.7", "commands": commands}
    api = run([prefix / "bin/cpg-zstd-api-probe"])
    details = dict(line.split("=", 1) for line in api.splitlines() if "=" in line)
    if Path(details["library"]).resolve(strict=True).parent != prefix / "lib":
        raise RuntimeError("The API probe loaded a shared library outside the selected prefix")
    if details.get("version") != "1.5.7" or details.get("one_shot_cases") != "15" or details.get("streaming_workers") != "2":
        raise RuntimeError("Incomplete installed C API coverage")
    with tempfile.TemporaryDirectory(prefix="cpg-zstd-check-") as directory:
        work = Path(directory)
        sample = work / "input with spaces.bin"
        original = bytes(range(256)) * 4096 + b"Zstandard native frame\x00"
        sample.write_bytes(original)
        for level in (1, 3, 9):
            frame, restored = work / f"level-{level}.zst", work / f"restored-{level}.bin"
            run([cli, "-q", "-T2", f"-{level}", "--check", sample, "-o", frame])
            run([cli, "-q", "-t", frame])
            run([cli, "-q", "-d", frame, "-o", restored])
            if restored.read_bytes() != original:
                raise RuntimeError("CLI decompression changed the input bytes")
            damaged = work / f"damaged-{level}.zst"
            damaged.write_bytes(frame.read_bytes()[:-1])
            run([cli, "-q", "-t", damaged], expected="nonzero")
        samples = work / "samples"
        samples.mkdir()
        for i in range(96):
            text = "".join(json.dumps({"event": j % 17, "customer": i, "path": f"/records/{j % 31}",
                                        "payload": "a repeated native dictionary training record " * 3}) + "\n"
                           for j in range(12))
            (samples / f"sample-{i:03d}.jsonl").write_text(text)
        dictionary = work / "trained.dict"
        run([cli, "-q", "--train", *sorted(samples.iterdir()), "-o", dictionary, "--maxdict=2048"])
        frame, restored = work / "dictionary.zst", work / "dictionary-restored.bin"
        chosen = samples / "sample-010.jsonl"
        run([cli, "-q", "-D", dictionary, chosen, "-o", frame])
        run([cli, "-q", "-d", "-D", dictionary, frame, "-o", restored])
        if restored.read_bytes() != chosen.read_bytes():
            raise RuntimeError("Dictionary round trip changed the input bytes")
        run([cli, "-q", "-t", frame], expected="nonzero")
    share = prefix / "share/compiler-playground/zstd"
    good = sorted((share / "golden-decompression").glob("*.zst"))
    bad = sorted((share / "golden-decompression-errors").glob("*.zst"))
    if len(good) != 4 or len(bad) != 3:
        raise RuntimeError("The preserved upstream golden-frame set is incomplete")
    for frame in good:
        run([cli, "-q", "-t", frame])
    for frame in bad:
        run([cli, "-q", "-t", frame], expected="nonzero")
    return {"status": "passed", "kind": "functional", "api": details,
            "golden_valid_frames": len(good), "golden_invalid_frames": len(bad),
            "input_sha256": hashlib.sha256(original).hexdigest(),
            "scope": "Native Zstd CLI/library, content checksums, two-worker streaming, dictionary training/use and original upstream decoder regression frames.",
            "benchmark_score": None, "commands": commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, version_only=args.version_only), indent=2))


if __name__ == "__main__":
    main()
