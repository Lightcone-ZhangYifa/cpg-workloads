#!/usr/bin/env python3
"""Run a child with debuginfod disabled and kernel-enforced socket denial.

Linux + libseccomp are required. Failure to install the guard is fatal; it never
silently falls back to a merely advisory environment flag.
"""
import ctypes
import ctypes.util
import errno
import os
import sys

def install_guard():
    path=ctypes.util.find_library('seccomp')
    if not path:
        raise RuntimeError('libseccomp is required for offline execution')
    lib=ctypes.CDLL(path, use_errno=True)
    lib.seccomp_init.argtypes=[ctypes.c_uint32]
    lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    lib.seccomp_rule_add.restype=ctypes.c_int
    lib.seccomp_load.argtypes=[ctypes.c_void_p]
    lib.seccomp_load.restype=ctypes.c_int
    lib.seccomp_release.argtypes=[ctypes.c_void_p]
    context=lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('seccomp_init failed')
    try:
        for syscall in ('socket','socketpair','connect','bind','listen','accept','accept4','sendto','sendmsg','sendmmsg','io_uring_setup'):
            number=lib.seccomp_syscall_resolve_name(syscall.encode())
            if number < 0:
                continue
            rc=lib.seccomp_rule_add(context,0x50000 | errno.EPERM,number,0)
            if rc != 0:
                raise RuntimeError(f'seccomp_rule_add {syscall} failed: {rc}')
        rc=lib.seccomp_load(context)
        if rc != 0:
            raise RuntimeError(f'seccomp_load failed: {rc}')
    finally:
        lib.seccomp_release(context)

def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: offline_exec.py COMMAND [ARG ...]')
    os.environ['DEBUGINFOD_URLS']=''
    os.environ['DEBUGINFOD_URLS_FILE']='/dev/null'
    os.environ['DEBUGINFOD_PROGRESS']='0'
    os.environ['CPG_CPG_EXAMPLE_OFFLINE']='seccomp-deny-sockets'
    install_guard()
    os.execvp(sys.argv[1], sys.argv[1:])

if __name__=='__main__':
    main()
