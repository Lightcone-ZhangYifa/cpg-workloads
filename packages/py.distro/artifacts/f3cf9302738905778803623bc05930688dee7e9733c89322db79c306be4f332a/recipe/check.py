#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Parse controlled os-release fixtures without host distribution assumptions."""
    fixture = work / "os-release"
    fixture.write_text('NAME="Example Linux"\nID=example\nID_LIKE="debian ubuntu"\nVERSION_ID="24.04"\nVERSION="24.04 (Research)"\nVERSION_CODENAME=research\nPRETTY_NAME="Example Linux 24.04"\n')
    distribution = module.LinuxDistribution(include_lsb=False, include_uname=False, include_oslevel=False, os_release_file=str(fixture), distro_release_file=str(work / "absent-release"))
    require(distribution.id() == "example" and distribution.name(pretty=True) == "Example Linux 24.04", "Distribution identity parsing failed")
    require(distribution.version() == "24.04" and distribution.version_parts() == ("24", "04", ""), "Version fields failed")
    require(distribution.like() == "debian ubuntu" and distribution.codename() == "research", "Like/codename failed")
    require(distribution.os_release_info()["id"] == "example", "Raw os-release information failed")
    empty = work / "empty"; empty.write_text("")
    absent = module.LinuxDistribution(include_lsb=False, include_uname=False, include_oslevel=False, os_release_file=str(empty), distro_release_file=str(work / "missing"))
    require(absent.id() == "" and absent.version() == "", "Empty fixture falsely produced an identity")
    return {"checks": ["fixture-identity", "pretty-name", "version-components", "like-codename", "raw-fields", "empty-input"], "host-distro-assumed": False}

if __name__ == "__main__":
    raise SystemExit(main('distro', 'distro', functional))
