#!/usr/bin/env python3
"""Install original FlameGraph scripts with the exact historical private Perl.

This performs no machine-code compilation and no host package transaction.
Original Debian inputs and source scripts remain unmodified. Absolute links in
the private installed tree are made relative while retaining an explicit map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def relative_name(value):
    path = PurePosixPath(value)
    need(not path.is_absolute() and ".." not in path.parts, "Unsafe Debian archive member")
    return Path(*[part for part in path.parts if part not in ("", ".")])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "prefix", "build"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    source, prefix, build = args.source.resolve(), args.prefix.resolve(), args.build.resolve()
    recipe = Path(__file__).resolve().parent
    shutil.copytree(source, prefix, dirs_exist_ok=True, symlinks=True)
    original = [{"path": path.relative_to(source).as_posix(), "bytes": path.stat().st_size,
                 "mode": path.stat().st_mode & 0o777, "sha256": sha(path)}
                for path in sorted(source.rglob("*")) if path.is_file() and not path.is_symlink()]
    need(original, "Original source is empty")
    share = prefix / "share/flamegraph"
    share.mkdir(parents=True)
    runtime, raw_inputs = share / "runtime", share / "debs"
    runtime.mkdir()
    raw_inputs.mkdir()
    declarations = json.loads((recipe / "private-deb-inputs.json").read_text())
    need(declarations["count"] == len(declarations["requirements"]) == 21, "Expected exact 21-package historical Perl closure")
    commands, inputs, pending_links, pending_hardlinks, link_changes = [], [], {}, {}, []
    logs = build / "private-perl-unpack-logs"
    logs.mkdir()

    def command(argv, label):
        result = subprocess.run([str(value) for value in argv], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        (logs / (label + ".stdout")).write_bytes(result.stdout)
        (logs / (label + ".stderr")).write_bytes(result.stderr)
        commands.append({"label": label, "argv": list(map(str, argv)), "returncode": result.returncode})
        save(logs / "commands.json", commands)
        need(result.returncode == 0, "Failed command: " + label)
        return result

    observed_decoder = command(["/usr/bin/dpkg-deb", "--version"], "decoder-version").stdout.decode()
    for row in declarations["requirements"]:
        declaration = row["source"]
        raw = recipe / "vendor" / Path(declaration["material_path"]).name
        need(raw.is_file() and raw.stat().st_size == row["bytes"] and sha(raw) == row["sha256"], "Pinned Debian input changed: " + row["resource_id"])
        shutil.copy2(raw, raw_inputs / raw.name)
        result = command(["/usr/bin/dpkg-deb", "--field", raw, "Package", "Version", "Architecture"], row["resource_id"] + "-identity")
        actual = dict(line.split(": ", 1) for line in result.stdout.decode().splitlines())
        expected = {"Package": row["package_name"], "Version": row["version"], "Architecture": row["architecture"]}
        need(actual == expected, "Debian control metadata differs: " + row["resource_id"])
        with (logs / (row["resource_id"] + "-decode.stderr")).open("wb") as error_log:
            process = subprocess.Popen(["/usr/bin/dpkg-deb", "--fsys-tarfile", str(raw)], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=error_log)
            members = 0
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    relative = relative_name(member.name)
                    if not relative.parts:
                        continue
                    target = runtime / relative
                    need(not any(parent.is_symlink() for parent in target.parents if parent != runtime.parent), "Archive writes through a link")
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        target.chmod(member.mode & 0o777)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as reader, target.open("wb") as writer:
                            shutil.copyfileobj(reader, writer)
                        target.chmod(member.mode & 0o777)
                        pending_links.pop(relative.as_posix(), None)
                        pending_hardlinks.pop(relative.as_posix(), None)
                    elif member.issym():
                        pending_links[relative.as_posix()] = member.linkname
                    elif member.islnk():
                        pending_hardlinks[relative.as_posix()] = relative_name(member.linkname).as_posix()
                    else:
                        raise ValueError("Unsupported Debian member kind: " + member.name)
                    members += 1
            process.stdout.close()
            need(process.wait(timeout=60) == 0, "Debian decoding failed: " + row["resource_id"])
        inputs.append({"resource_id": row["resource_id"], "sha256": row["sha256"], "bytes": row["bytes"], "filename": raw.name,
                       "observed_metadata": actual, "decoded_members": members})
    for name, original_target in sorted(pending_links.items()):
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            need(not path.is_dir(), "Link would replace an installed directory")
            path.unlink()
        if original_target.startswith("/"):
            target = runtime / original_target.lstrip("/")
            link = os.path.relpath(target, path.parent)
        else:
            link = original_target
        need((path.parent / link).resolve().is_relative_to(runtime), "A private link escapes the runtime: " + name)
        path.symlink_to(link)
        if link != original_target:
            link_changes.append({"path": name, "original_target": original_target, "installed_target": link})
    for name, target in sorted(pending_hardlinks.items()):
        source_path = runtime / target
        need(source_path.is_file() and source_path.resolve().is_relative_to(runtime), "Missing Debian hardlink target")
        target_path = runtime / name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    inactive_links = []
    for path in runtime.rglob("*"):
        if path.is_symlink():
            need(path.resolve().is_relative_to(runtime), "Private-runtime link escapes its root: " + str(path))
            if not path.exists():
                # Debian's unpacked closure includes inactive integration links
                # (rmt alternatives and a Perl changelog alias). No dpkg
                # configuration transaction is performed here. Their original
                # entries remain in the unchanged retained .deb files and this
                # explicit map; they must not masquerade as working links.
                relative = path.relative_to(runtime).as_posix()
                expected = {"etc/rmt": "../usr/sbin/rmt", "usr/share/doc/perl/Changes.gz": "changelog.gz"}
                need(relative in expected and os.readlink(path) == expected[relative], "Unexpected unresolved runtime link: " + relative)
                inactive_links.append({"path": relative, "target": os.readlink(path), "status": "not_activated; original entry retained in fixed Debian inputs"})
                path.unlink()
    save(share / "inactive-debian-links.json", inactive_links)
    perl = runtime / "usr/bin/perl"
    loaders = [path for path in runtime.rglob("ld-linux-x86-64.so.2") if path.is_file() and not path.is_symlink()]
    need(perl.is_file() and len(loaders) == 1, "Exactly one private Perl loader is required")
    loader = loaders[0]
    library_directories = [name for name in ("usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu") if (runtime / name).is_dir()]
    library_path = ":".join(str(runtime / name) for name in library_directories)
    resolved = command([loader, "--library-path", library_path, "--list", perl], "private-library-resolution")
    libraries = []
    for line in resolved.stdout.decode().splitlines():
        match = re.search(r"=> (/\S+)\s+\(", line)
        if match:
            path = Path(match.group(1)).resolve()
            need(path.is_relative_to(runtime), "Private Perl loaded a host shared library")
            libraries.append({"path": path.relative_to(runtime).as_posix(), "sha256": sha(path)})
    need(libraries, "No private library resolutions were recorded")
    include_directories = ["usr/lib/x86_64-linux-gnu/perl/5.38.2", "usr/share/perl/5.38.2"]
    need(all((runtime / name).is_dir() for name in include_directories), "Exact Perl module directories are missing")
    bootstrap = share / "perl-bootstrap"
    bootstrap.mkdir()
    (bootstrap / "CPGPrivatePerl.pm").write_text("BEGIN { my $root=$ENV{CPG_PRIVATE_PERL_ROOT}; die \"Missing private root\" unless defined $root; @INC=(\"$root/usr/lib/x86_64-linux-gnu/perl/5.38.2\",\"$root/usr/share/perl/5.38.2\"); }\n1;\n")
    bindir = prefix / "bin"
    bindir.mkdir(exist_ok=True)
    launcher = bindir / "flamegraph-perl"
    launcher.write_text("#!/bin/sh\nroot=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
        "runtime=\"$root/share/flamegraph/runtime\"\nunset PERL5OPT PERL5LIB PERLLIB LD_PRELOAD LD_LIBRARY_PATH\n"
        "CPG_PRIVATE_PERL_ROOT=\"$runtime\"\nexport CPG_PRIVATE_PERL_ROOT\n"
        "exec \"$runtime/" + loader.relative_to(runtime).as_posix() + "\" --library-path \"" + ":".join("$runtime/" + name for name in library_directories) + "\" \"$runtime/usr/bin/perl\" -f -I\"$root/share/flamegraph/perl-bootstrap\" -MCPGPrivatePerl \"$@\"\n")
    launcher.chmod(0o755)
    for name, script in (("flamegraph", "flamegraph.pl"), ("stackcollapse-perf", "stackcollapse-perf.pl"), ("difffolded", "difffolded.pl")):
        path = bindir / name
        path.write_text("#!/bin/sh\nroot=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\nexec \"$root/bin/flamegraph-perl\" \"$root/" + script + "\" \"$@\"\n")
        path.chmod(0o755)
    for name in ("check.py", "check_original.py", "script-locks.json", "private-deb-inputs.json"):
        shutil.copy2(recipe / name, share / name)
    profile = {"schema_version": 1, "resource_id": "flamegraph", "version": "commit-41fee1f99f92", "private_deb_inputs": inputs,
        "original_source_inventory": original, "private_perl": {"path": perl.relative_to(runtime).as_posix(), "sha256": sha(perl),
            "loader": loader.relative_to(runtime).as_posix(), "loader_sha256": sha(loader), "upstream_version": "5.38.2",
            "library_directories": library_directories, "resolved_libraries": libraries, "include_directories": include_directories},
        "installed_link_relocations": link_changes, "inactive_system_integration_links": inactive_links,
        "machine_code_compilation": "not_applicable; interpreted scripts and original precompiled Debian runtime",
        "host_apt_transaction": "not_run", "host_perl_used": False, "observed_decoder": {"path": "/usr/bin/dpkg-deb", "sha256": sha(Path("/usr/bin/dpkg-deb")), "version_output": observed_decoder},
        "scope": "Exact historical Perl runtime and unchanged FlameGraph source; only explicit installed entry points are qualified"}
    save(share / "profile.json", profile)
    print(json.dumps({"status": "passed", "private_deb_packages": len(inputs), "original_source_files": len(original), "machine_code_compilation": "not_applicable"}))


if __name__ == "__main__":
    main()
