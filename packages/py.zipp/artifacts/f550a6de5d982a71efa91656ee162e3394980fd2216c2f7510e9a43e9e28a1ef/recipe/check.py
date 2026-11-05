#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Read a real ZIP through pathlib-style traversal and missing-file errors.'
    import zipfile
    archive = work / "sample.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("data/one.txt", "hello 雪")
        output.writestr("data/two.bin", b"\x00\x01")
    with zipfile.ZipFile(archive) as opened:
        root = module.Path(opened)
        folder = root / "data"
        require(folder.is_dir() and {entry.name for entry in folder.iterdir()} == {"one.txt", "two.bin"}, "Virtual directory traversal failed")
        require((folder / "one.txt").read_text(encoding="utf-8") == "hello 雪", "ZIP text read failed")
        require((folder / "two.bin").read_bytes() == b"\x00\x01", "ZIP binary read failed")
        missing = folder / "absent.txt"
        require(not missing.exists(), "Missing member reported present")
        raises(FileNotFoundError, lambda: missing.read_bytes(), "Missing member read was accepted")
    return {"checks": ["real-zip-creation", "implicit-directory-traversal", "unicode-text-read", "binary-read", "missing-member"]}

if __name__ == '__main__':
    raise SystemExit(main('zipp', 'zipp', functional))
