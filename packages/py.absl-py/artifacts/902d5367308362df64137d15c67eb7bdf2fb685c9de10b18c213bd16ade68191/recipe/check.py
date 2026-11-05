#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise independent flags, typed parsing, validators and invalid input."""
    flags = installed_module("absl.flags")
    values = flags.FlagValues()
    flags.DEFINE_integer("count", 1, "Work count", lower_bound=1, upper_bound=8, flag_values=values)
    flags.DEFINE_enum("mode", "cpu", ["cpu", "gpu"], "Mode", flag_values=values)
    flags.DEFINE_boolean("enabled", False, "Enable work", flag_values=values)
    remainder = values(["program", "--count=4", "--mode=gpu", "--enabled", "input"])
    require(values.count == 4 and values.mode == "gpu" and values.enabled, "Flag parsing mismatch")
    require(remainder == ["program", "input"], "Positional remainder mismatch")
    raises(flags.IllegalFlagValueError, lambda: values(["program", "--count=0"]), "Range failure accepted")
    raises(flags.IllegalFlagValueError, lambda: values(["program", "--mode=tpu"]), "Invalid enum accepted")
    raises(flags.UnrecognizedFlagError, lambda: values(["program", "--missing=yes"]), "Unknown flag accepted")
    other = flags.FlagValues()
    flags.DEFINE_integer("count", 7, "Independent count", flag_values=other)
    other(["program"])
    require(other.count == 7, "Independent flag namespace failed")
    return {"checks": ["typed-flags", "positional-remainder", "range-validator", "enum-validator", "unknown-option", "independent-flag-namespace"]}

if __name__ == "__main__":
    raise SystemExit(main('absl-py', 'absl', functional))
