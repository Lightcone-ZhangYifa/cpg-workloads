"""Exercise the selected XZ tools, both liblzma forms, and real NLS messages."""
from __future__ import annotations
import _lzma
import argparse
import ctypes
import gettext
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import tempfile


def check(prefix: Path, *, version_only=False):
    prefix = prefix.resolve(strict=True)
    library = prefix / "lib/liblzma.so.5.8.4"
    selected = ctypes.CDLL(str(library))
    selected.lzma_version_string.restype = ctypes.c_char_p
    version = selected.lzma_version_string().decode("ascii")
    if version != "5.8.4":
        raise RuntimeError("Selected liblzma has the wrong version: " + version)
    env = dict(os.environ, LC_ALL="C", PATH=str(prefix / "bin") + ":/usr/bin:/bin", XZ=str(prefix / "bin/xz"))
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "XZ_DEFAULTS", "XZ_OPT", "LANGUAGE"):
        env.pop(key, None)
    commands = []

    def run(argv, *, data=None, expected=0, environment=None):
        argv = [str(p) for p in argv]
        result = subprocess.run(argv, input=data, capture_output=True, env=environment or env, timeout=60)
        row = {"argv": argv, "returncode": result.returncode,
               "stdin_bytes": None if data is None else len(data),
               "stdin_sha256": None if data is None else hashlib.sha256(data).hexdigest(),
               "stdout_bytes": len(result.stdout), "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
               "stderr": result.stderr.decode("utf-8", "replace")}
        commands.append(row)
        if (expected == "nonzero" and result.returncode == 0) or (expected != "nonzero" and result.returncode != expected):
            raise RuntimeError(json.dumps(row))
        return result.stdout

    robot = run([prefix / "bin/xz", "--robot", "--version"]).decode("ascii")
    reported = dict(line.split("=", 1) for line in robot.splitlines() if "=" in line)
    selected.lzma_version_number.restype = ctypes.c_uint32
    if reported != {"XZ_VERSION": str(selected.lzma_version_number()), "LIBLZMA_VERSION": str(selected.lzma_version_number())}:
        raise RuntimeError("xz and the selected liblzma versions disagree: " + repr(reported))
    if version_only:
        return {"status": "passed", "kind": "version", "version": version,
                "library": str(library), "robot": reported, "commands": commands}
    profile = json.loads((prefix / "share/compiler-playground/xz/profile.json").read_text())
    if profile.get("relocatable") is not False or Path(profile["fixed_prefix"]) != prefix:
        raise RuntimeError("The complete upstream XZ/NLS binary profile requires its declared fixed prefix")
    api = []
    for linkage in ("shared", "static"):
        probe = prefix / ("bin/cpg-xz-api-probe" + ("-static" if linkage == "static" else ""))
        output = run([probe]).decode("ascii")
        details = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        expected_parent = prefix / ("lib" if linkage == "shared" else "bin")
        if (Path(details["library"]).resolve(strict=True).parent != expected_parent or
                details.get("version") != "5.8.4" or details.get("linkage") != linkage or
                details.get("one_shot_cases") != "45" or details.get("multithreaded_encoder_threads") != "2"):
            raise RuntimeError("Installed API probe selected another library or incomplete coverage")
        api.append(details)
    original = bytes(range(256)) * 4096 + b"xz package independent reference\x00"
    cli = prefix / "bin/xz"
    with tempfile.TemporaryDirectory(prefix="cpg-xz-check-") as directory:
        work = Path(directory)
        for name, kind in (("crc32", lzma.CHECK_CRC32), ("crc64", lzma.CHECK_CRC64), ("sha256", lzma.CHECK_SHA256)):
            for level in (1, 6, 9):
                compressed = run([cli, "-c", f"-{level}", "--check=" + name,
                                  "--threads=2", "--block-size=256KiB"], data=original)
                if lzma.decompress(compressed) != original:
                    raise RuntimeError("Python lzma disagrees with the installed xz output")
            reference = lzma.compress(original, format=lzma.FORMAT_XZ, check=kind, preset=6)
            if run([cli, "-dc", "--threads=2"], data=reference) != original:
                raise RuntimeError("Installed xz disagrees with the Python reference")
            damaged = bytearray(reference)
            damaged[-1] ^= 0xff
            run([cli, "-dc"], data=bytes(damaged), expected="nonzero")
            run([cli, "-dc"], data=reference[:-5], expected="nonzero")
        sample = work / "sample.xz"
        sample.write_bytes(compressed)
        listing = run([cli, "--robot", "--list", "-vv", sample]).decode("ascii")
        if "\nfile\t" not in listing or "\nblock\t" not in listing:
            raise RuntimeError("Machine-readable file/block listing is incomplete")
        for tool in ("xzdec", "xzcat"):
            if run([prefix / "bin" / tool], data=compressed) != original:
                raise RuntimeError("Installed decoder tool failed: " + tool)
        legacy = run([cli, "--format=lzma", "-c", "-6"], data=original)
        if lzma.decompress(legacy, format=lzma.FORMAT_ALONE) != original:
            raise RuntimeError("Python rejected installed LZMA-Alone output")
        reference = lzma.compress(original, format=lzma.FORMAT_ALONE, preset=6)
        for tool in ("lzmadec", "lzcat"):
            if run([prefix / "bin" / tool], data=reference) != original:
                raise RuntimeError("Installed legacy decoder failed: " + tool)
        run([prefix / "bin/lzmainfo"], data=legacy)
        text = b"compiler-playground-nls-check\n"
        first, second = work / "first.xz", work / "second.xz"
        first.write_bytes(run([cli, "-c"], data=text))
        second.write_bytes(first.read_bytes())
        if text.strip() not in run([prefix / "bin/xzgrep", text.strip().decode(), first]):
            raise RuntimeError("Installed xzgrep could not read the selected compressor's stream")
        run([prefix / "bin/xzdiff", first, second])
        second.write_bytes(run([cli, "-c"], data=b"different content\n"))
        run([prefix / "bin/xzdiff", first, second], expected=1)
    locale_file = prefix / "share/locale/de/LC_MESSAGES/xz.mo"
    with locale_file.open("rb") as stream:
        translation = gettext.GNUTranslations(stream)
    english = "Compress or decompress FILEs in the .xz format."
    german = translation.gettext(english)
    if german == english:
        raise RuntimeError("The installed German message catalog contains no expected translation")
    german_env = dict(env, LC_ALL="C.UTF-8", LANGUAGE="de")
    help_output = run([cli, "--help"], environment=german_env).decode("utf-8")
    if german not in help_output:
        raise RuntimeError("The installed xz executable did not use its own German message catalog")
    info_output = run([prefix / "bin/lzmainfo", "--help"], environment=german_env).decode("utf-8")
    if "Aufruf:" not in info_output:
        raise RuntimeError("The installed lzmainfo executable did not use its German catalog")
    base_utilities = {}
    for name in ("grep", "diff", "sed"):
        path = Path("/usr/bin") / name
        base_utilities[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "version_output": run([path, "--version"]).decode("utf-8")}
    reference_path = Path(_lzma.__file__)
    return {"status": "passed", "kind": "functional", "api": api,
            "reference": {"implementation": "Python lzma with the observed host liblzma binding",
                          "extension": str(reference_path), "extension_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest()},
            "fixed_prefix": str(prefix), "nls": {"status": "passed", "language": "de", "locale": "C.UTF-8",
                            "catalog": str(locale_file), "catalog_sha256": hashlib.sha256(locale_file.read_bytes()).hexdigest(),
                            "observed_message": german},
            "base_utilities": base_utilities, "commands": commands, "benchmark_score": None,
            "not_run": ["Interactive pager use of xzmore/xzless", "po4a translated man-page generation",
                        "Cross-container installation", "Timing/benchmark qualification"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.prefix, version_only=args.version_only), indent=2))


if __name__ == "__main__":
    main()
