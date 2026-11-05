#!/usr/bin/env python3
"""Installed functional check for filelock; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(fl, work):
    """Prove contention and release using a second real Python process."""
    import sys
    path = work / "shared.lock"
    script = "import sys; from filelock import FileLock, Timeout; lock=FileLock(sys.argv[1]);\ntry:\n with lock.acquire(timeout=0.2): print('acquired')\nexcept Timeout:\n print('blocked'); sys.exit(7)\n"
    lock = fl.FileLock(path)
    with lock:
        result = child([sys.executable, "-I", "-c", script, path], expected=7)
        require(result.stdout.strip() == "blocked", "Contending process did not report lock timeout")
        require(lock.is_locked, "Owner unexpectedly lost the lock")
    result = child([sys.executable, "-I", "-c", script, path])
    require(result.stdout.strip() == "acquired" and not lock.is_locked, "Released lock remained unavailable")
    return {"checks": ["real-process-contention", "timeout-exit-status", "release-and-reacquire"], "filesystem_scope": "selected local temporary directory; network filesystems not qualified"}

if __name__ == "__main__":
    raise SystemExit(main('filelock', 'filelock', functional))
