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
        for tool in ('gcc', 'ar', 'nm', 'readelf', 'objcopy', 'objdump', 'addr2line', 'dpkg-deb', 'ldd'):
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
        self.run('elfutils-version',[self.prefix/'usr/bin/eu-readelf','--version'])
        self.run('runtime-linkage-elfutils',['ldd',self.prefix/'usr/bin/eu-readelf'])
        return lock

    def binutils(self):
        examples=ROOT/'examples'
        common=['gcc','-Wall','-Wextra','-Werror','-g','-gdwarf-4','-O0','-fno-pie','-fno-omit-frame-pointer']
        self.run('compile-elf-main',common+['-c',examples/'elf_fixture.c','-o','fixture.o'])
        self.run('compile-elf-impl',common+['-c',examples/'math_impl.c','-o','math_impl.o'])
        self.run('archive-impl',['ar','rcs','libimpl.a','math_impl.o'])
        self.run('link-fixture',['gcc','-no-pie','-Wl,--build-id','fixture.o','libimpl.a','-o','fixture'])
        result=self.run('run-fixture',[self.build/'fixture'])
        self.need('cpg_example-result=23' in result,'ELF fixture produced an incorrect result')
        header=self.run('elf-header',['readelf','-hW','fixture'])
        self.need('ELF64' in header and 'X86-64' in header,'Unexpected object target')
        reloc=self.run('object-relocations',['readelf','-rW','fixture.o'])
        self.need('external_transform' in reloc,'Object does not retain the intended external-call relocation')
        symbols=self.run('symbols',['nm','-n','fixture'])
        self.need(' T cpg_example_entry' in symbols and ' T external_transform' in symbols,'Missing linked fixture symbols')
        disassembly=self.run('disassembly',['objdump','-d','fixture'])
        self.need('<cpg_example_entry>' in disassembly and '<external_transform>' in disassembly,'Missing call-site disassembly')
        address=re.search(r'^([0-9a-fA-F]+) T cpg_example_entry$',symbols,re.M).group(1)
        self.address='0x'+address
        self.run('keep-debug',['objcopy','--only-keep-debug','fixture','fixture.debug'])
        self.run('strip-debug',['objcopy','--strip-debug','fixture','fixture.stripped'])
        self.run('debuglink',['objcopy','--add-gnu-debuglink=fixture.debug','fixture.stripped'])
        sections=self.run('stripped-sections',['readelf','-SW','fixture.stripped'])
        self.need('.gnu_debuglink' in sections and '.debug_info' not in sections,'Detached debug sections are incorrect')
        self.run('dump-debuglink',['objcopy','--dump-section','.gnu_debuglink=debuglink.bin','fixture.stripped'])
        link=(self.build/'debuglink.bin').read_bytes()
        end=link.index(0)
        name=link[:end].decode()
        crc_offset=(end+1+3)&~3
        crc=struct.unpack_from('<I',link,crc_offset)[0]
        expected=zlib.crc32((self.build/'fixture.debug').read_bytes()) & 0xffffffff
        self.need(name=='fixture.debug' and crc==expected,'GNU debuglink filename/CRC mismatch')
        lines=self.run('gnu-addr2line',['addr2line','-f','-e','fixture.debug',self.address])
        self.need('cpg_example_entry' in lines and 'elf_fixture.c:' in lines,'GNU addr2line failed source resolution')
        (self.build/'truncated.elf').write_bytes((self.build/'fixture').read_bytes()[:31])
        self.run('reject-truncated-elf',['readelf','-hW','truncated.elf'],expected=1)
        self.capabilities['apt.binutils']={'status':'passed','scope':'host-version supplementary ELF workflow',
            'gnu_debuglink_crc32':f'{crc:08x}','formal_qualification_changed':False,
            'frozen_version':'2.42-4ubuntu2.10','observed_host_package_version':self.host_binutils_package_version,
            'host_differs_from_frozen_version':self.host_binutils_package_version!='2.42-4ubuntu2.10' if self.host_binutils_package_version else None}

    def elfutils(self):
        tool=self.prefix/'usr/bin'
        info=self.run('eu-dwarf-info',[tool/'eu-readelf','--debug-dump=info','fixture'])
        self.need('cpg_example_entry' in info,'elfutils could not find fixture DWARF')
        location=self.run('eu-addr2line',[tool/'eu-addr2line','-f','-e','fixture.stripped',self.address])
        self.need('cpg_example_entry' in location and 'elf_fixture.c:' in location,'elfutils failed local debuglink lookup')
        self.run('eu-unstrip',[tool/'eu-unstrip','-o','fixture.restored','fixture.stripped','fixture.debug'])
        restored=self.run('restored-sections',['readelf','-SW','fixture.restored'])
        self.need('.debug_info' in restored,'eu-unstrip did not restore debug sections')
        (self.build/'fixture.restored').chmod(0o755)
        self.run('run-restored',[self.build/'fixture.restored'])
        self.run('elflint',[tool/'eu-elflint','--gnu-ld','fixture'])
        self.run('eu-reject-truncated',[tool/'eu-readelf','-h','truncated.elf'],expected=1)
        hostile=dict(self.env,DEBUGINFOD_URLS='https://invalid.cpg_example.example/')
        code='import os,socket; assert os.environ["DEBUGINFOD_URLS"]==""; assert os.environ["DEBUGINFOD_URLS_FILE"]=="/dev/null"; print("environment override verified");\ntry: socket.socket()\nexcept PermissionError: print("socket blocked by kernel");\nelse: raise SystemExit("socket unexpectedly allowed")'
        previous=self.env
        try:
            self.env=hostile
            probe=self.run('hostile-debuginfod-env',[sys.executable,ROOT/'scripts/offline_exec.py',sys.executable,'-c',code])
        finally:
            self.env=previous
        self.need('environment override verified' in probe and 'socket blocked by kernel' in probe,'Offline isolation probe failed')
        self.capabilities['apt.elfutils']={'status':'passed','scope':'local ELF/DWARF/debuglink; no core/remote unwinding claims',
            'network_policy':'DEBUGINFOD_URLS empty plus seccomp denial','formal_qualification_changed':False}

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
        runner.binutils()
        runner.elfutils()
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
