#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Resolve isolated XDG application directories with actual directory creation.'
    import os
    names = {"XDG_CACHE_HOME": str(work / "cache"), "XDG_CONFIG_HOME": str(work / "config"), "XDG_DATA_HOME": str(work / "data")}
    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update(names)
        dirs = module.PlatformDirs("cpg-probe", appauthor=False, version="7", ensure_exists=True)
        for value, key in [(dirs.user_cache_dir, "XDG_CACHE_HOME"), (dirs.user_config_dir, "XDG_CONFIG_HOME"), (dirs.user_data_dir, "XDG_DATA_HOME")]:
            expected = Path(names[key]) / "cpg-probe" / "7"
            require(Path(value) == expected and expected.is_dir(), "Selected XDG directory/creation mismatch")
        require(Path(module.user_cache_dir("cpg-probe", appauthor=False)).parent == work / "cache", "Functional directory helper ignored XDG override")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return {"checks": ["xdg-cache", "xdg-config", "xdg-data", "version-subdirectory", "directory-creation", "functional-helper"]}

if __name__ == '__main__':
    raise SystemExit(main('platformdirs', 'platformdirs', functional))
