"""Build the full pinned native ITT SDK and a documented GNU/Linux adaptation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from gnu_fortran import generate

CPP_TESTS = ("test_string_handle", "test_domain", "test_task", "test_region",
             "test_frame", "test_collection_control", "test_thread_naming", "test_ittapi")
ORACLE_SHA = "74a47309829844187278d1d8565701928d288c90d5683b4d429fe7eb1060c65e"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "prefix"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    source, build, prefix = (p.resolve() for p in (args.source, args.build, args.prefix))
    recipe = Path(__file__).resolve().parent
    native, logs = build / "native", build / "recipe-logs"
    logs.mkdir()
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C", SOURCE_DATE_EPOCH="0", PYTHONDONTWRITEBYTECODE="1")
    for key in list(env):
        if key.startswith("INTEL_LIBITTNOTIFY") or key in {"CC", "CXX", "FC", "F77", "CFLAGS", "CXXFLAGS", "FFLAGS", "LDFLAGS", "LD_PRELOAD", "CMAKE_PREFIX_PATH"}:
            env.pop(key)
    cmake = Path(env.get("CPG_CMAKE", "/usr/bin/cmake"))
    ninja = Path(env.get("CPG_NINJA", "/usr/bin/ninja"))
    fc = Path(env.get("CPG_GFORTRAN", "/usr/bin/gfortran"))
    ctest = cmake.parent / "ctest"
    commands = []
    def run(label, argv, timeout=600):
        row = {"label": label, "argv": [str(x) for x in argv], "cwd": str(build)}
        started = time.monotonic()
        with (logs / (label + ".log")).open("w") as stream:
            result = subprocess.run(row["argv"], cwd=build, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        row.update(returncode=result.returncode, seconds=time.monotonic()-started, log=str(logs / (label + ".log")))
        commands.append(row)
        (build / "recipe-log.json").write_text(json.dumps(commands, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            raise RuntimeError("Native ITT build failed: " + label)
    mapflag = "-ffile-prefix-map=" + str(source) + "=/usr/src/ittapi -ffile-prefix-map=" + str(build) + "=/usr/build/ittapi"
    run("configure", [cmake, "-S", source, "-B", native, "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + str(ninja),
        "-DCMAKE_C_COMPILER=/usr/bin/cc", "-DCMAKE_CXX_COMPILER=/usr/bin/c++", "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_FLAGS=" + mapflag, "-DCMAKE_CXX_FLAGS=" + mapflag,
        "-DCMAKE_INSTALL_PREFIX=" + str(prefix), "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DITT_API_CPP_SUPPORT=ON", "-DITT_API_REFERENCE_COLLECTOR=ON", "-DITT_API_REFCOL_SMOKE_TESTS=ON",
        "-DITT_API_FORTRAN_SUPPORT=OFF"])
    run("build", [cmake, "--build", native, "--parallel", args.jobs])
    run("upstream-cpp-tests", [ctest, "--test-dir", native / "cpp", "--output-on-failure", "--output-junit", logs / "cpp-junit.xml"])
    tests = ET.parse(logs / "cpp-junit.xml").findall(".//testcase")
    if {r.attrib["name"] for r in tests} != {"cpp_" + name for name in CPP_TESTS} or len(tests) != 8 or any(r.find("failure") is not None or r.find("skipped") is not None for r in tests):
        raise RuntimeError("Upstream C++ test inventory is missing, duplicated or incomplete")
    run("install", [cmake, "--install", native])
    share = prefix / "share/ittapi"
    share.mkdir(parents=True)
    shutil.copytree(source / "LICENSES", share / "LICENSES")
    shutil.copytree(source / "include/fortran", share / "fortran")
    shutil.copy2(source / "README.md", share / "README.md")
    shutil.copy2(source / "src/ittnotify_refcol/README.md", share / "reference-collector.md")
    probes = share / "qualification"
    probes.mkdir()
    for path in recipe.iterdir():
        if path.suffix in {".py", ".c", ".cpp", ".f90"}:
            shutil.copy2(path, probes / path.name)
    oracle = source / "src/ittnotify_refcol/tests/run_smoke_test.py"
    if hashlib.sha256(oracle.read_bytes()).hexdigest() != ORACLE_SHA:
        raise RuntimeError("Pinned official reference collector oracle changed")
    shutil.copy2(oracle, probes / "official_refcol_test.py")
    shutil.copy2(source / "src/ittnotify_refcol/tests/smoke_test.c", probes / "official_refcol_smoke.c")
    # The upstream smoke client explicitly initializes all ITT groups using this
    # internal enum header. Keep its exact prerequisite beside the test source,
    # rather than adding a private upstream header to the public include API.
    shutil.copy2(source / "src/ittnotify/ittnotify_types.h", probes / "ittnotify_types.h")
    (prefix / "bin").mkdir(exist_ok=True)
    for name in ("libjitprofiling.a", "libittnotify_refcol.so"):
        shutil.copy2(native / "bin" / name, prefix / "lib" / name)
    shutil.copy2(native / "bin/refcol_smoke_test", prefix / "bin/refcol_smoke_test")
    for name in CPP_TESTS:
        shutil.copy2(native / "cpp" / name, probes / name)
    generated = share / "fortran-gnu"
    adaptation = generate(source / "include/fortran", generated)
    modules = prefix / "include/ittapi-fortran"
    modules.mkdir()
    for name, obj in (("ittnotify", "ittfortran"), ("advisor_annotate", "advisor_annotate")):
        run("fortran-module-" + name, [fc, "-O2", "-g0", "-fPIC", "-ffree-line-length-none", "-J" + str(modules),
                                     "-c", generated / (name + ".f90"), "-o", prefix / "lib" / (obj + ".o")])
    base = [fc, "-O2", "-g0", "-I" + str(modules)]
    # GNU BIND(C) globals otherwise satisfy the linker without extracting the
    # initialized ITT object from the static archive. Whole-archive is deliberate.
    run("fortran-client", base + [recipe / "fortran_probe.f90", prefix / "lib/ittfortran.o",
        "-Wl,--whole-archive", prefix / "lib/libittnotify.a", "-Wl,--no-whole-archive", "-ldl", "-pthread", "-o", probes / "fortran_probe"])
    run("advisor-client", base + [recipe / "advisor_probe.f90", prefix / "lib/advisor_annotate.o", "-ldl", "-o", probes / "advisor_probe"])
    run("advisor-abi-fixture", ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-fPIC", "-shared", "-Werror", "-I" + str(prefix / "include"),
                               recipe / "advisor_fixture.c", "-o", probes / "advisor_fixture.so"])
    run("sync-abi-fixture", ["/usr/bin/cc", "-std=c11", "-O2", "-g0", "-Werror", "-I" + str(prefix / "include"), "-c", recipe / "sync_fixture.c", "-o", build / "sync_fixture.o"])
    run("sync-client", base + [recipe / "sync_probe.f90", prefix / "lib/ittfortran.o", build / "sync_fixture.o", "-o", probes / "sync_probe"])
    run("cpp-client", ["/usr/bin/c++", "-std=c++17", "-O2", "-g0", "-I" + str(prefix / "include"), recipe / "cpp_probe.cpp",
                       prefix / "lib/libittnotify.a", "-ldl", "-pthread", "-o", probes / "cpp_probe"])
    version_text = (prefix / "lib/cmake/ittapi/ittapiConfigVersion.cmake").read_text()
    cmake_version = re.search(r'set\(PACKAGE_VERSION "([^"]+)"\)', version_text).group(1)
    if cmake_version != "3.0.0":
        raise RuntimeError("Pinned upstream ABI/config version changed")
    profile = {"schema_version": 1, "id": "intel-ittapi", "version": "3.28.4", "upstream_commit": "bd72cfb15e34a5fc4c0a8d10f5bb5305d60e1eec",
        "upstream_c_api": "3.0", "upstream_cmake_config_version": cmake_version, "gnu_fortran_compiler": "13.3.0",
        "fortran_adaptation": adaptation, "official_oracle_sha256": ORACLE_SHA, "cpp_tests": list(CPP_TESTS),
        "source_ctest_count": len(tests), "reference_collector": True,
        "advisor_runtime": "ABI fixture only; Intel Advisor/VTune not qualified, reference collector has no model API.",
        "fortran_public_lock_ids": "Original default-integer IDs retained; not a new 64-bit-address interface.",
        "python_distribution": "not_installed; separately versioned 1.2.2 alternative release artifact",
        "optional_ipt": "upstream default OFF; original default unchanged",
        "relocation": "Installed CMake metadata is relative; collector is selected explicitly; no global environment or loader-cache modification."}
    (share / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")


if __name__ == "__main__":
    main()
