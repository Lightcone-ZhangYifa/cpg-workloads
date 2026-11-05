#!/usr/bin/env python3
"""Keep command-local runtime libraries and pkg-config paths inside this prefix."""
import argparse
from pathlib import Path
import re


def finalize(prefix):
    prefix = prefix.resolve()
    runtime = prefix / "libexec/resource-binaries"
    runtime.mkdir(parents=True, exist_ok=True)
    wrapped = []
    for binary in sorted((prefix / "bin").iterdir()):
        if binary.is_symlink() or not binary.is_file():
            continue
        with binary.open("rb") as stream:
            is_elf = stream.read(4) == b"\x7fELF"
        if not is_elf:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", binary.name):
            raise ValueError("Unsupported installed command name")
        target = runtime / binary.name
        binary.replace(target)
        wrapper = ("#!/bin/sh\n"
                   "bindir=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd) || exit 1\n"
                   "prefix=$(dirname -- \"$bindir\")\n"
                   "LD_LIBRARY_PATH=\"$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"\n"
                   "export LD_LIBRARY_PATH\n"
                   "exec \"$prefix/libexec/resource-binaries/" + binary.name + "\" \"$@\"\n")
        binary.write_text(wrapper)
        binary.chmod(0o755)
        wrapped.append(binary.name)
    for metadata in (prefix / "lib/pkgconfig").glob("*.pc"):
        value = metadata.read_text()
        value = re.sub(r"^prefix=.*$", "prefix=${pcfiledir}/../..", value, count=1, flags=re.MULTILINE)
        metadata.write_text(value)
    # These two upstream shell tools also embed configure's absolute prefix.
    # Preserve their implementations and resolve only that location at launch.
    for name in ("hwloc-gather-topology", "hwloc-compress-dir"):
        script = prefix / "bin" / name
        value = script.read_text()
        replacement = 'prefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd) || exit 1'
        value, count = re.subn(r"^prefix=.*$", lambda _: replacement, value, count=1, flags=re.MULTILINE)
        if count != 1:
            raise ValueError("Missing upstream prefix assignment in " + name)
        script.write_text(value)
    return wrapped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    print("Installed local runtime launchers: " + ", ".join(finalize(args.prefix)))


if __name__ == "__main__":
    main()
