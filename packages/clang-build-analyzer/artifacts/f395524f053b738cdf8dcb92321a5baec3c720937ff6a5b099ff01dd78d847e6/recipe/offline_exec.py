#!/usr/bin/env python3
"""Execute a local command with new IPv4/IPv6 sockets denied by seccomp.

Linux-only verification helper. AF_UNIX remains available. This is an offline
test guard, not a general security sandbox or a resource-isolation claim.
"""
import argparse
import ctypes
import ctypes.util
import errno
import os
import socket
import sys


class ArgCompare(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_uint),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def install_filter():
    path = ctypes.util.find_library("seccomp")
    if not path:
        raise RuntimeError("libseccomp is required; refusing an unguarded run")
    lib = ctypes.CDLL(path, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_int, ctypes.c_uint,
                                         ctypes.POINTER(ArgCompare)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError("seccomp_init failed")
    try:
        syscall = lib.seccomp_syscall_resolve_name(b"socket")
        if syscall < 0:
            raise RuntimeError("socket syscall could not be resolved")
        for family in (socket.AF_INET, socket.AF_INET6):
            args = (ArgCompare * 1)(ArgCompare(0, 4, family, 0))  # SCMP_CMP_EQ
            rc = lib.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM,
                                           syscall, 1, args)
            if rc != 0:
                raise OSError(-rc, "seccomp_rule_add_array failed")
        rc = lib.seccomp_load(ctx)
        if rc != 0:
            raise OSError(-rc, "seccomp_load failed")
    finally:
        lib.seccomp_release(ctx)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    install_filter()
    os.execvp(command[0], command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f"offline_exec: {error}", file=sys.stderr)
        sys.exit(125)
