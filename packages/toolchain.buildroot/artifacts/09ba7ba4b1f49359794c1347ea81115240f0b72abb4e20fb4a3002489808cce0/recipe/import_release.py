#!/usr/bin/env python3
"""Import a fixed prebuilt release; this performs no source compilation/download."""
import argparse
from pathlib import Path, PurePosixPath
import tarfile
import subprocess


def inspect_tar(path, allow_skeleton_links=False):
    """Check names, links and file types before using GNU tar for ownership-safe extraction."""
    with tarfile.open(path) as tf:
        members = tf.getmembers()
    names = set()
    links = set()
    roots = set()
    for x in members:
        name = PurePosixPath(x.name)
        if name.is_absolute() or ".." in name.parts or not name.parts:
            raise ValueError("Unsafe archive member: " + x.name)
        roots.add(name.parts[0])
        if x.name in names and not x.isdir():
            raise ValueError("Duplicate archive member: " + x.name)
        names.add(x.name)
        if not (x.isfile() or x.isdir() or x.issym() or x.islnk()):
            raise ValueError("Special file in archive: " + x.name)
        if x.issym():
            target = PurePosixPath(x.linkname)
            if target.is_absolute():
                if not (allow_skeleton_links and "/skeleton" in x.name):
                    raise ValueError("Absolute archive symlink: " + x.name)
            else:
                parts = list(name.parts[:-1])
                for component in target.parts:
                    if component == "..":
                        if len(parts) <= 1:
                            raise ValueError("Escaping archive symlink: " + x.name)
                        parts.pop()
                    elif component != ".":
                        parts.append(component)
            links.add(name)
        elif x.islnk():
            target = PurePosixPath(x.linkname)
            if target.is_absolute() or ".." in target.parts or not target.parts:
                raise ValueError("Unsafe hard link")
    for x in members:
        if any(p in links for p in PurePosixPath(x.name).parents):
            raise ValueError("Archive writes through a symbolic link: " + x.name)
    if len(roots) != 1:
        raise ValueError("Expected exactly one archive root")
    return next(iter(roots))


def extract(path, destination, allow_skeleton_links=False):
    inspect_tar(path, allow_skeleton_links)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "--no-same-owner", "-xf", str(path), "--strip-components=1",
                    "-C", str(destination)], check=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive")
    p.add_argument("prefix")
    a = p.parse_args()
    extract(a.archive, a.prefix)
    print("Fixed prebuilt release imported; no upstream compiler source build was performed.")
