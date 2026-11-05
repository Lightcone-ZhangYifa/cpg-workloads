#!/usr/bin/env python3
"""Replay this software's supplementary examples in a fresh private output tree.

Never installs packages, writes in its payload, accesses the network, or changes
the CPG catalog. Every executed command has a raw stdout/stderr evidence file.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import traceback
import zlib

sys.dont_write_bytecode = True
from offline_exec import install_guard

ROOT = Path(__file__).resolve().parents[1]

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class Runner:
    def __init__(self, output):
        self.output=output
        self.logs=output/'logs'
        self.build=output/'build'
        self.prefix=output/'prefix'
        for path in (self.logs,self.build,self.prefix): path.mkdir()
        self.env=dict(os.environ)
        self.env.update({'LC_ALL':'C','LANG':'C','DEBUGINFOD_URLS':'',
            'DEBUGINFOD_URLS_FILE':'/dev/null','DEBUGINFOD_PROGRESS':'0',
            'DEBUGINFOD_CACHE_PATH':str(output/'debuginfod-cache'),
            'PYTHONDONTWRITEBYTECODE':'1'})
        self.commands=[]
        self.capabilities={}

    def run(self, name, command, expected=0):
        command=[str(x) for x in command]
        start=time.monotonic()
        result=subprocess.run(command,cwd=self.build,env=self.env,text=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
        log=self.logs/f'{len(self.commands)+1:03d}-{name}.txt'
        log.write_text('ARGV: '+json.dumps(command)+'\nEXIT: '+str(result.returncode)+
            '\n--- STDOUT ---\n'+result.stdout+'\n--- STDERR ---\n'+result.stderr)
        record={'name':name,'argv':command,'returncode':result.returncode,
            'seconds':round(time.monotonic()-start,6),
            'log':log.relative_to(self.output).as_posix()}
        self.commands.append(record)
        accepted=result.returncode != 0 if expected=='nonzero' else (result.returncode in expected if isinstance(expected,tuple) else result.returncode==expected)
        if not accepted: raise RuntimeError(f'{name}: exit {result.returncode}, expected {expected}; {log}')
        return result.stdout

    def need(self, condition, message):
        if not condition: raise AssertionError(message)

    def prepare(self):
        self.need(platform.machine()=='x86_64','This frozen amd64 supplementary environment requires x86_64 Linux')
        self.need(platform.system()=='Linux','The offline guard requires Linux')
        for tool in ('gcc', 'readelf', 'dpkg-deb', 'ldd'):
            self.need(shutil.which(tool),f'Missing host prerequisite: {tool}')
        lock=json.loads((ROOT/'metadata/inputs.lock.json').read_text())
        for row in lock['inputs']:
            path=(ROOT/row['path']).resolve()
            self.need(path.is_relative_to(ROOT),'Input lock path escapes payload')
            self.need(path.is_file(),f'Missing pinned input: {row["path"]}')
            self.need(path.stat().st_size==row['bytes'],f'Size mismatch: {row["path"]}')
            self.need(sha256(path)==row['sha256'],f'SHA256 mismatch: {row["path"]}')
        sources=json.loads((ROOT/'metadata/sources.lock.json').read_text())
        for source in sources['source_sets']:
            for row in source['files']:
                path=(ROOT/row['path']).resolve()
                self.need(path.is_relative_to(ROOT),'Source lock path escapes payload')
                self.need(path.is_file() and path.stat().st_size==row['bytes'],f'Missing/size mismatch corresponding source: {row["path"]}')
                self.need(sha256(path)==row['sha256'],f'Corresponding source SHA256 mismatch: {row["path"]}')
        for row in lock['inputs']:
            path=ROOT/row['path']
            self.run('extract-'+row['name'],['dpkg-deb','-x',path,self.prefix])
            self.run('metadata-'+row['name'],['dpkg-deb','-f',path])
        self.library=self.prefix/'usr/lib/x86_64-linux-gnu'
        self.env['LD_LIBRARY_PATH']=str(self.library)
        self.env['PATH']=str(self.prefix/'usr/bin')+os.pathsep+self.env.get('PATH','')
        self.run('host-gcc-version',['gcc','--version'])
        self.run('host-binutils-version',['readelf','--version'])
        self.host_binutils_package_version=None
        if shutil.which('dpkg-query'):
            self.host_binutils_package_version=self.run('host-binutils-package-version',['dpkg-query','-W','-f=${Version}','binutils'],expected=(0,1)).strip() or None
        return lock

    def libunwind(self):
        inc=self.prefix/'usr/include'
        common=['gcc','-Wall','-Wextra','-Werror','-g','-rdynamic','-fasynchronous-unwind-tables',
            '-fno-optimize-sibling-calls','-I'+str(inc),'-I'+str(inc/'x86_64-linux-gnu')]
        modes={'fp':['-O0','-fno-omit-frame-pointer'],'cfi':['-O2','-fomit-frame-pointer']}
        diagnostics={}
        for mode,flags in modes.items():
            name='unwind-'+mode
            self.run('compile-'+name,common+flags+[ROOT/'examples/unwind_local.c','-L'+str(self.library),'-lunwind','-o',name])
            linkage=self.run('linkage-'+name,['ldd',name])
            self.need('not found' not in linkage and str(self.library/'libunwind.so.8') in linkage,'Unexpected libunwind runtime provider')
            result=self.run('run-'+name,[self.build/name])
            self.need('middle=1 outer=1 main=1 terminal=0' in result,'Expected local frames were not recovered')
            diagnostics[mode]={'symbol_lookup_unavailable_frames':result.count('symbol_unavailable='),
                'frame_oracle':'ordered return IPs independently captured by GCC __builtin_return_address(0)'}
        frames=self.run('unwind-cfi-records',['readelf','--debug-dump=frames','unwind-cfi'])
        self.need('FDE' in frames and 'CIE' in frames,'CFI-based test executable has no frame records')
        self.capabilities['apt.libunwind-dev']={'status':'passed','scope':'nongnu libunwind local x86_64 call-chain recovery',
            'modes':['frame-pointer','omit-frame-pointer-with-CFI'],
            'diagnostics':diagnostics,
            'not_claimed':['LLVM libunwind identity','remote/core unwind','C++ exception ABI conformance','symbol lookup when runtime reports unavailable'],
            'formal_qualification_changed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New directory outside the installed material')
    args=parser.parse_args()
    output=args.output.resolve()
    if output==ROOT or output.is_relative_to(ROOT):
        parser.error('--output must be outside the installed material')
    output.mkdir(parents=True,exist_ok=False)
    runner=Runner(output)
    identity=json.loads((ROOT/'metadata/software-identity.json').read_text())
    receipt={'schema_version':1,'resource_id':identity['id'],'version':identity['version'],
        'scope':identity['scope'],'host':{'platform':platform.platform(),'machine':platform.machine(),'python':sys.version},
        'formal_qualification_changed':False,'status':'running'}
    try:
        install_guard()
        for family in (socket.AF_INET,socket.AF_INET6):
            try:
                stream=socket.socket(family)
            except PermissionError:
                pass
            else:
                stream.close()
                raise RuntimeError('Offline kernel filter did not deny socket creation')
        receipt['network_guard']={'mechanism':'libseccomp deny socket/connect/send and io_uring_setup',
            'ipv4_socket_denied':True,'ipv6_socket_denied':True,'debuginfod_urls':''}
        receipt['inputs']=runner.prepare()
        runner.libunwind()
        receipt['status']='passed'
    except Exception as error:
        receipt['status']='failed'
        receipt['error']=str(error)
        (output/'failure.txt').write_text(traceback.format_exc())
    finally:
        receipt['capabilities']={key:value for key,value in runner.capabilities.items() if key==identity['id']}
        receipt['prerequisite_capabilities']={key:value for key,value in runner.capabilities.items() if key!=identity['id']}
        receipt['commands']=runner.commands
        receipt['command_count']=len(runner.commands)
        receipt['artifacts']=[{'path':path.relative_to(output).as_posix(),'sha256':sha256(path),'bytes':path.stat().st_size}
            for path in sorted(runner.build.rglob('*')) if path.is_file()]
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({'status':receipt['status'],'resource_id':identity['id'],
            'command_count':len(runner.commands),'receipt':str(output/'receipt.json')},ensure_ascii=False))
    return 0 if receipt['status']=='passed' else 1

if __name__=='__main__':
    raise SystemExit(main())
