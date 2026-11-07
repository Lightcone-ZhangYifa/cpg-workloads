#!/usr/bin/env python3
"""Deny IP socket creation with inherited Linux seccomp; preserve local IPC."""
import ctypes
import ctypes.util
import errno
import json
import os
import socket
import sys

class ScmpArgCmp(ctypes.Structure):
    _fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),
              ('datum_a',ctypes.c_uint64),('datum_b',ctypes.c_uint64)]

def install():
    name=ctypes.util.find_library('seccomp')
    if not name:
        raise RuntimeError('libseccomp unavailable; cannot claim enforced offline execution')
    lib=ctypes.CDLL(name,use_errno=True)
    lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(ScmpArgCmp)]
    lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_release.argtypes=[ctypes.c_void_p]
    context=lib.seccomp_init(0x7fff0000)
    if not context:
        raise RuntimeError('seccomp_init failed')
    try:
        for syscall in [b'socket',b'socketpair']:
            number=lib.seccomp_syscall_resolve_name(syscall)
            if number<0:
                raise RuntimeError('Unresolved syscall '+syscall.decode())
            for family in [socket.AF_INET,socket.AF_INET6]:
                compare=ScmpArgCmp(0,4,int(family),0)
                code=lib.seccomp_rule_add_array(context,0x00050000|errno.EPERM,number,1,ctypes.byref(compare))
                if code:
                    raise RuntimeError('seccomp rule failed '+str(code))
        code=lib.seccomp_load(context)
        if code:
            raise RuntimeError('seccomp_load failed '+str(code))
    finally:
        lib.seccomp_release(context)
    results={}
    for family in [socket.AF_INET,socket.AF_INET6]:
        try:
            s=socket.socket(family,socket.SOCK_STREAM)
        except PermissionError as exc:
            if exc.errno!=errno.EPERM:
                raise
            results[str(family)]='denied-EPERM'
        else:
            s.close()
            raise RuntimeError('Network socket was not denied')
    pair=socket.socketpair()
    try:
        pair[0].sendall(b'CPG')
        if pair[1].recv(3)!=b'CPG':
            raise RuntimeError('Local IPC probe failed')
    finally:
        for sock in pair:sock.close()
    return {'policy':'AF_INET and AF_INET6 socket/socketpair denied with EPERM; AF_UNIX preserved',
            'inheritance':'kernel filter inherited by subprocesses','self_test':results,'af_unix':'passed'}

if __name__=='__main__':
    result=install()
    print(json.dumps(result),flush=True)
    if len(sys.argv)>1:
        os.execvp(sys.argv[1],sys.argv[1:])
