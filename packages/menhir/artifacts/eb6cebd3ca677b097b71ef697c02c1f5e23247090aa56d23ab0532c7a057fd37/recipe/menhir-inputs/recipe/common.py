"""Shared local-only build helpers. No network imports or download commands."""
import datetime
import hashlib
import json
import os
import platform
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "_work"
EVIDENCE = ROOT / "evidence"


def configure(source=None, build=None, evidence=None):
    global ROOT, WORK, EVIDENCE
    ROOT = Path(source).resolve() if source else ROOT
    WORK = Path(build).resolve() if build else ROOT / "_work"
    EVIDENCE = Path(evidence).resolve() if evidence else (WORK / "evidence" if build else ROOT / "evidence")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    return ROOT, WORK, EVIDENCE


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_inputs():
    lock = json.loads((ROOT / "materials/sources.lock.json").read_text())
    for item in lock["sources"] + lock["metadata"]:
        p = ROOT / item["path"]
        if not p.is_file() or sha256(p) != item["sha256"]:
            raise RuntimeError("Missing or modified locked input: " + item["path"])
    return lock


def unpack(item, dest):
    marker = dest / ".cpg-source-sha256"
    if marker.exists():
        if marker.read_text().strip() != item["sha256"]:
            raise RuntimeError("Refusing mismatching source work tree: " + str(dest))
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ROOT / item["path"]) as tar:
        names = tar.getnames()
        tops = {n.split("/")[0] for n in names}
        if len(tops) != 1:
            raise RuntimeError("Expected a single top-level source directory")
        top = next(iter(tops))
        temp = dest.parent / (dest.name + "-extract")
        temp.mkdir(exist_ok=True)
        tar.extractall(temp, filter="data")
        (temp / top).rename(dest)
        temp.rmdir()
    marker.write_text(item["sha256"] + "\n")
    return dest


def run(command, cwd, logfile, env=None, timeout=3600):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log = EVIDENCE / logfile
    start = time.monotonic()
    with log.open("w") as f:
        f.write("$ " + repr([str(c) for c in command]) + "\n")
        f.write("cwd=" + str(cwd) + "\n")
        f.flush()
        p = subprocess.run([str(c) for c in command], cwd=cwd, env=env,
                           stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    result = {"command": [str(c) for c in command], "cwd": str(cwd),
              "returncode": p.returncode, "seconds": round(time.monotonic() - start, 3),
              "log": str(log), "log_sha256": sha256(log)}
    print(json.dumps(result), flush=True)
    if p.returncode:
        print(log.read_text(errors="replace")[-12000:], flush=True)
        raise RuntimeError("Command failed; see " + str(log))
    return result


def environment(prefix):
    env = dict(os.environ)
    # Pin compiler discovery; do not inherit another user's opam switch.
    for key in ("OPAM_SWITCH_PREFIX", "OCAMLPATH", "OCAML_TOPLEVEL_PATH", "CAML_LD_LIBRARY_PATH"):
        env.pop(key, None)
    env["PATH"] = str(prefix / "bin") + ":/usr/bin:/bin"
    env["OCAMLLIB"] = str(prefix / "lib/ocaml")
    env["LC_ALL"] = "C"
    env["DUNE_CACHE"] = "disabled"
    env["DUNE_CONFIG__PKG_BUILD_PROGRESS"] = "disabled"
    return env


def host_info():
    info = {"platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(),
            "network": "No network code or package solver is invoked by build/install/check. Sandbox enforcement is provided by the calling environment and is not probed here."}
    for name, command in (("cc", ["cc", "--version"]), ("make", ["make", "--version"]),
                          ("libc", ["ldd", "--version"]), ("ld", ["ld", "--version"])):
        p = subprocess.run(command, capture_output=True, text=True)
        info[name] = (p.stdout + p.stderr).splitlines()[0]
    return info


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
