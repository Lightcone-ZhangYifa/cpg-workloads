#!/usr/bin/env python3
"""Build the explicit non-assembler libjpeg-turbo profile without downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--jobs", type=int, required=True)
    args = parser.parse_args()
    cmake = Path(os.environ.get("CPG_CMAKE", "/usr/bin/cmake")).resolve()
    ninja = Path(os.environ.get("CPG_NINJA", "/usr/bin/ninja")).resolve()
    ctest = cmake.with_name("ctest")
    evidence = args.prefix / "share/compiler-playground/libjpeg-turbo"
    evidence.mkdir(parents=True)
    commands = []

    def run(label, argv):
        command = [str(v) for v in argv]
        print(json.dumps({"label": label, "argv": command}), flush=True)
        with (evidence / (label + ".stdout")).open("wb") as out, (evidence / (label + ".stderr")).open("wb") as err:
            result = subprocess.run(command, stdout=out, stderr=err)
        commands.append({"label": label, "argv": command, "returncode": result.returncode})
        (evidence / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError("Build command failed: " + label)
        return (evidence / (label + ".stdout")).read_text()

    run("configure", [cmake, "-S", args.source, "-B", args.build, "-G", "Ninja",
        "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=/usr/bin/gcc", "-DCMAKE_C_FLAGS=-march=x86-64 -mtune=generic",
        "-DCMAKE_INSTALL_PREFIX=" + str(args.prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib",
        "-DENABLE_SHARED=ON", "-DENABLE_STATIC=ON", "-DWITH_SIMD=OFF",
        "-DWITH_TURBOJPEG=ON", "-DWITH_TOOLS=ON", "-DWITH_TESTS=ON",
        "-DWITH_ARITH_ENC=ON", "-DWITH_ARITH_DEC=ON", "-DWITH_SYSTEM_SPNG=OFF",
        "-DWITH_SYSTEM_ZLIB=OFF", "-DWITH_FUZZ=OFF"])
    run("build", [cmake, "--build", args.build, "--parallel", args.jobs])
    available = json.loads(run("ctest-list", [ctest, "--test-dir", args.build, "--show-only=json-v1"]))
    if len(available.get("tests", [])) < 100:
        raise RuntimeError("The complete upstream regression matrix was not configured")
    run("ctest", [ctest, "--test-dir", args.build, "--parallel", args.jobs,
        "--output-on-failure", "--timeout", "180", "--output-junit", evidence / "upstream-tests.xml"])
    suite = ET.parse(evidence / "upstream-tests.xml").getroot()
    cases = list(suite.iter("testcase"))
    if len(cases) != len(available["tests"]) or any(c.find("failure") is not None or c.find("error") is not None or c.find("skipped") is not None for c in cases):
        raise RuntimeError("Upstream CTest evidence is incomplete or contains failures/skips")
    run("install", [cmake, "--install", args.build])
    # Upstream overrides CMAKE_INSTALL_RPATH with the absolute installation
    # directory. CMake's own ELF metadata editor replaces that exact field;
    # original source and codec instructions are unchanged.
    rpath_changes = []
    for directory in (args.prefix / "bin", args.prefix / "lib"):
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
            observed = subprocess.run(["/usr/bin/readelf", "-d", str(path)], check=True, capture_output=True, text=True).stdout
            old = str(args.prefix / "lib")
            if old not in observed:
                continue
            new = "$ORIGIN/../lib" if path.parent.name == "bin" else "$ORIGIN"
            script = args.build / ("relocate-" + path.name + ".cmake")
            script.write_text('file(RPATH_CHANGE FILE "' + str(path) + '" OLD_RPATH "' + old + '" NEW_RPATH "' + new + '")\n')
            run("relocate-" + path.name, [cmake, "-P", script])
            after = subprocess.run(["/usr/bin/readelf", "-d", str(path)], check=True, capture_output=True, text=True).stdout
            if old in after or "[" + new + "]" not in after:
                raise RuntimeError("The installed ELF retained an absolute build prefix")
            rpath_changes.append({"path": path.relative_to(args.prefix).as_posix(), "old": old, "new": new,
                                  "readelf_before": observed, "readelf_after": after})
    if not any(row["path"] == "bin/cjpeg" for row in rpath_changes):
        raise RuntimeError("The upstream executable RPATH contract changed")
    (evidence / "rpath-changes.json").write_text(json.dumps(rpath_changes, indent=2) + "\n")
    for path in (args.prefix / "lib/pkgconfig").glob("*.pc"):
        lines = path.read_text().splitlines()
        expected = {"prefix": str(args.prefix), "exec_prefix": str(args.prefix),
                    "libdir": str(args.prefix / "lib"), "includedir": str(args.prefix / "include")}
        replacements = {"prefix": "${pcfiledir}/../..", "exec_prefix": "${prefix}",
                        "libdir": "${prefix}/lib", "includedir": "${prefix}/include"}
        for key, value in expected.items():
            original = key + "=" + value
            if lines.count(original) != 1:
                raise RuntimeError("Unexpected pkg-config field: " + key)
            lines[lines.index(original)] = key + "=" + replacements[key]
        path.write_text("\n".join(lines) + "\n")
    shutil.copytree(args.source, args.prefix / "share/libjpeg-turbo/source")
    for name in ("check.py", "api.c"):
        shutil.copy2(Path(__file__).with_name(name), evidence / name)
    (evidence / "profile.json").write_text(json.dumps({
        "id": "libjpeg-turbo", "version": "3.2.0", "profile": "scalar-full-codec",
        "source_modified": False, "shared_and_static": True,
        "simd": "disabled explicitly; pinned assembler is not in the existing catalog",
        "turbojpeg": True, "arithmetic_coding": True, "bundled_png_and_zlib": True,
        "upstream_ctest_passed": len(cases), "upstream_ctest_skipped": 0,
        "library_abi": "libjpeg v6b and TurboJPEG 3", "rpath": "$ORIGIN/../lib",
        "unperformed": ["NASM/Yasm SIMD profile", "JNA/Java", "cross-architecture", "physical performance qualification"]
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
