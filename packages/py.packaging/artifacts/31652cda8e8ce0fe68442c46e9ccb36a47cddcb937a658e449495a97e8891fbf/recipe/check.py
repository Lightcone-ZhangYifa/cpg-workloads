#!/usr/bin/env python3
"""Installed functional check for packaging; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(packaging, work):
    """Evaluate explicit packaging examples and reject malformed identities."""
    from packaging.version import Version, InvalidVersion
    from packaging.specifiers import SpecifierSet
    from packaging.requirements import Requirement, InvalidRequirement
    from packaging.utils import parse_wheel_filename
    require(Version("1.0rc1") < Version("1.0") < Version("1.0.post1"), "Version ordering mismatch")
    spec = SpecifierSet(">=2,<3")
    require("2.5" in spec and "3.0" not in spec, "Specifier mismatch")
    requirement = Requirement('example[fast]>=2; python_version >= "3.11"')
    require(requirement.extras == {"fast"} and requirement.marker.evaluate({"python_version": "3.12"}), "Requirement parsing mismatch")
    name, version, build, tags = parse_wheel_filename("example-1.0-py3-none-any.whl")
    require(str(name) == "example" and str(version) == "1.0" and bool(tags), "Wheel identity mismatch")
    raises(InvalidVersion, lambda: Version("not a version"), "Bad version was accepted")
    raises(InvalidRequirement, lambda: Requirement("!!!"), "Bad requirement was accepted")
    return {"checks": ["version-order", "specifier", "requirement-marker", "wheel-tags", "invalid-version", "invalid-requirement"]}

if __name__ == "__main__":
    raise SystemExit(main('packaging', 'packaging', functional))
