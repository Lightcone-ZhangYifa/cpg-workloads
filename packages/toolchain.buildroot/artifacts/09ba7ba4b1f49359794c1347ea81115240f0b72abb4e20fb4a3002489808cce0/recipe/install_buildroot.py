#!/usr/bin/env python3
"""Assemble exactly one Buildroot external toolchain from locked local inputs."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from import_release import extract
from prepare_host_tools import prepare

RUNTIME_LINKS = {
    "etc/mtab": "../proc/self/mounts",
    "etc/resolv.conf": "../run/resolv.conf",
    "dev/stdin": "../proc/self/fd/0",
    "dev/stdout": "../proc/self/fd/1",
    "dev/stderr": "../proc/self/fd/2",
    "dev/fd": "../proc/self/fd",
}


def project_runtime_links(sysroot, prefix, *, required):
    """Remove only exact dynamic target-runtime links; preserve all compiler inputs."""
    removed = []
    for relative, expected in RUNTIME_LINKS.items():
        path = sysroot / relative
        if not path.is_symlink() and not path.exists() and not required:
            continue
        if not path.is_symlink() or os.readlink(path) != expected:
            raise ValueError("Unexpected target-runtime link; refusing a broad cleanup: " + str(path))
        removed.append({"path": str(path.relative_to(prefix)), "target": expected,
                        "reason": "Dynamic target /proc or /run endpoint; absent in an offline development SDK"})
        path.unlink()
    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("assets", type=Path)
    parser.add_argument("build", type=Path)
    parser.add_argument("prefix", type=Path)
    args = parser.parse_args()
    assets, build, prefix = (path.resolve() for path in (args.assets, args.build, args.prefix))
    recipe = Path(__file__).resolve().parent
    source, sdk, output = build / "buildroot-source", prefix / "sdk", build / "buildroot-output"
    extract(assets / "raw/buildroot-2026.08.1.tar.xz", source, allow_skeleton_links=True)
    extract(assets / "raw/aarch64--musl--stable-2026.08-1.tar.xz", sdk)
    subprocess.run(["sh", str(sdk / "relocate-sdk.sh")], cwd=sdk, check=True)
    projected = project_runtime_links(sdk / "aarch64-buildroot-linux-musl/sysroot", prefix, required=True)
    host_materials = assets / "supporting-host"
    shutil.copy2(recipe / "host-input-lock.json", host_materials / "host-input-lock.json")
    host = build / "host-tools"
    prepare(host_materials, host, ["gawk", "libsigsegv2", "rsync", "libpopt0", "bc", "cpio"])
    # Expose only required commands; optional, unused host-tool probes must not
    # accidentally select an incomplete private CMake installation.
    host_bin = build / "host-bin"
    host_bin.mkdir()
    for name in ["gawk", "rsync", "bc", "cpio"]:
        candidate = host / "usr/bin" / name
        if not candidate.exists():
            candidate = host / "bin" / name
        if not candidate.exists():
            raise RuntimeError("Missing isolated helper: " + name)
        (host_bin / name).symlink_to(candidate)
    environment = os.environ.copy()
    environment.pop("LD_LIBRARY_PATH", None)
    environment["PATH"] = str(host_bin) + ":" + environment["PATH"]
    downloads = build / "downloads"
    extra = downloads / "musl-compat-headers"
    extra.mkdir(parents=True)
    shutil.copy2(assets / "raw/buildroot-extra/queue.h", extra / "queue.h")
    template = (recipe / "buildroot-aarch64-musl.defconfig.in").read_text()
    config = build / "locked.defconfig"
    config.write_text(template.replace("@SDK@", str(sdk)) + '\nBR2_HOST_DIR="' + str(prefix / "host") + '"\nBR2_DL_DIR="' + str(downloads) + '"\n')
    for phase, argv in [("defconfig", ["make", "-C", str(source), "O=" + str(output),
                                      "BR2_DEFCONFIG=" + str(config), "defconfig"]),
                        ("toolchain", ["make", "-C", str(source), "O=" + str(output), "toolchain", "-j1"])]:
        with (build / (phase + ".log")).open("w") as stream:
            subprocess.run(argv, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True)
    share = prefix / "share/cpg-buildroot"
    share.mkdir(parents=True)
    shutil.copy2(config, share / "defconfig")
    shutil.copy2(output / ".config", share / "resolved.config")
    projected += project_runtime_links(prefix / "host/aarch64-buildroot-linux-musl/sysroot", prefix, required=False)
    converted = []
    for directory, directories, files in os.walk(prefix, followlinks=False):
        for name in directories + files:
            link = Path(directory) / name
            if not link.is_symlink():
                continue
            target = os.readlink(link)
            if os.path.isabs(target) and Path(target).is_relative_to(prefix):
                link.unlink()
                link.symlink_to(os.path.relpath(target, link.parent))
                converted.append(str(link.relative_to(prefix)))
            if os.path.isabs(os.readlink(link)) or not link.resolve(strict=True).is_relative_to(prefix):
                raise ValueError("Unexpected unresolved or escaping installed link: " + str(link))
    (share / "development-projection.json").write_text(json.dumps({"schema_version": 1,
        "kind": "development_toolchain_sysroot_projection",
        "original_archive_sha256": "b388c480a48e8e9f9b99e3d14e69219c4d61e5a2424a82faecb88a015b781a60",
        "removed_runtime_only_links": projected,
        "original_archive_preserved": True,
        "scope": "Cross compilation and linking; not a complete runnable/bootable target root filesystem"}, indent=2) + "\n")
    (share / "assembly.json").write_text(json.dumps({"buildroot": "2026.08.1",
        "external_sdk": "aarch64--musl--stable-2026.08-1", "compiler_source_rebuild": False,
        "converted_internal_absolute_symlinks": converted}, indent=2) + "\n")
    print("Buildroot development toolchain/sysroot assembly completed; compiler source rebuild and target-rootfs execution were not performed.")


if __name__ == "__main__":
    main()
