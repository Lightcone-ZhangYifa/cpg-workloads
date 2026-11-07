#!/usr/bin/env python3
"""A small local-only HIPRTC client with Comgr-backed architecture validation.

ROCm 7.0.2 can crash for an unknown architecture string. Reject unsupported
targets before invoking the compiler. This module does not discover devices,
load kernels, install drivers, fetch packages or mix bitcode versions.
"""
import ctypes as C
from pathlib import Path


class OfflineCompiler:
    def __init__(self, prefix):
        self.prefix = Path(prefix).resolve()
        self.comgr = C.CDLL(str(self.prefix/'lib/libamd_comgr.so.3'), mode=C.RTLD_GLOBAL)
        self.hiprtc = C.CDLL(str(self.prefix/'lib/libhiprtc.so.7'), mode=C.RTLD_GLOBAL)
        api = self.comgr
        api.amd_comgr_get_isa_count.argtypes = [C.POINTER(C.c_size_t)]
        api.amd_comgr_get_isa_name.argtypes = [C.c_size_t, C.POINTER(C.c_char_p)]
        count = C.c_size_t()
        self._success(api.amd_comgr_get_isa_count(C.byref(count)), 'get ISA count')
        names = []
        for i in range(count.value):
            name = C.c_char_p()
            self._success(api.amd_comgr_get_isa_name(i, C.byref(name)), 'get ISA name')
            names.append(name.value.decode())
        self.supported_targets = tuple(sorted({name.split('--', 1)[-1] for name in names}))
        api = self.hiprtc
        api.hiprtcCreateProgram.argtypes = [C.POINTER(C.c_void_p), C.c_char_p, C.c_char_p,
                                           C.c_int, C.POINTER(C.c_char_p), C.POINTER(C.c_char_p)]
        api.hiprtcCompileProgram.argtypes = [C.c_void_p, C.c_int, C.POINTER(C.c_char_p)]
        api.hiprtcGetProgramLogSize.argtypes = [C.c_void_p, C.POINTER(C.c_size_t)]
        api.hiprtcGetProgramLog.argtypes = [C.c_void_p, C.c_void_p]
        api.hiprtcGetCodeSize.argtypes = [C.c_void_p, C.POINTER(C.c_size_t)]
        api.hiprtcGetCode.argtypes = [C.c_void_p, C.c_void_p]
        api.hiprtcGetBitcodeSize.argtypes = [C.c_void_p, C.POINTER(C.c_size_t)]
        api.hiprtcGetBitcode.argtypes = [C.c_void_p, C.c_void_p]
        api.hiprtcDestroyProgram.argtypes = [C.POINTER(C.c_void_p)]

    @staticmethod
    def _success(status, operation):
        if status != 0:
            raise RuntimeError(f'{operation} failed: status={status}')

    def validate_target(self, target):
        if target not in self.supported_targets:
            raise ValueError('Unsupported explicit target: '+str(target))
        return target

    def compile_cpp(self, source, *, target, headers=None, bitcode=False):
        self.validate_target(target)
        if not isinstance(source, str) or '\0' in source:
            raise ValueError('source must be a NUL-free string')
        headers = dict(headers or {})
        if any(not isinstance(k, str) or not isinstance(v, str) or '\0' in k+v for k, v in headers.items()):
            raise ValueError('header names/content must be NUL-free strings')
        names = (C.c_char_p*len(headers))(*(x.encode() for x in headers))
        contents = (C.c_char_p*len(headers))(*(x.encode() for x in headers.values()))
        program = C.c_void_p()
        api = self.hiprtc
        self._success(api.hiprtcCreateProgram(C.byref(program), source.encode(), b'cpg.hip',
                                               len(headers), contents, names), 'create program')
        try:
            options = [('--gpu-architecture='+target).encode(), b'-O2']
            if bitcode:
                options.append(b'-fgpu-rdc')
            options = (C.c_char_p*len(options))(*options)
            status = api.hiprtcCompileProgram(program, len(options), options)
            size = C.c_size_t()
            self._success(api.hiprtcGetProgramLogSize(program, C.byref(size)), 'get log size')
            buffer = C.create_string_buffer(size.value+1)
            self._success(api.hiprtcGetProgramLog(program, buffer), 'get log')
            log = buffer.value.decode(errors='replace')
            if status:
                raise RuntimeError(f'HIPRTC compilation failed: status={status}\n{log}')
            size = C.c_size_t()
            getsize = api.hiprtcGetBitcodeSize if bitcode else api.hiprtcGetCodeSize
            get = api.hiprtcGetBitcode if bitcode else api.hiprtcGetCode
            self._success(getsize(program, C.byref(size)), 'get output size')
            buffer = C.create_string_buffer(size.value)
            self._success(get(program, buffer), 'get output')
            return {'bytes': buffer.raw, 'log': log, 'target': target,
                    'kind': 'llvm-bitcode' if bitcode else 'amdgpu-code-object'}
        finally:
            self._success(api.hiprtcDestroyProgram(C.byref(program)), 'destroy program')
