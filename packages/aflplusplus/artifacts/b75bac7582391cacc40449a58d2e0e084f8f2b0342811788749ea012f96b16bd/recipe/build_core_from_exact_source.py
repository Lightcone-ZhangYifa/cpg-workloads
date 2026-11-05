#!/usr/bin/env python3
"""Offline build a deliberately reduced AFL++ 5.03c core, never full distrib.

This recipe is a host-only QA adaptation and does not change original catalogs.
"""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,sys,time
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--prefix',required=True);p.add_argument('--jobs',type=int,required=True)
a=p.parse_args()
source=pathlib.Path(a.source).resolve(strict=True)
prefix=pathlib.Path(a.prefix)
assert (source/'GNUmakefile').is_file()
assert (source/'README.md').read_text().find('5.03c')>=0
assert a.jobs>=1
TOOLS=('afl-fuzz','afl-showmap','afl-tmin','afl-analyze','afl-cmin','afl-gotcpu')
command=['make',f'-j{a.jobs}',*TOOLS]
# Each target is a concrete non-optional upstream Make target, so any failure
# returns nonzero. Unlike upstream binary-only, no ignored FRIDA/QEMU download.
started=time.monotonic()
r=subprocess.run(command,cwd=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=240)
print('upstream_make_command',json.dumps(command));print('upstream_make_exit',r.returncode)
print('upstream_make_stdout_tail',r.stdout[-2400:]);print('upstream_make_stderr_tail',r.stderr[-2400:])
if r.returncode!=0:sys.exit(r.returncode or 3)
(prefix/'bin').mkdir(parents=True,exist_ok=True)
(prefix/'share/doc/aflplusplus').mkdir(parents=True,exist_ok=True)
sha={}
for name in TOOLS:
 f=source/name
 if not f.is_file() or not f.read_bytes()[:4]==b'\x7fELF':raise RuntimeError('Expected compiled ELF is missing '+name)
 shutil.copy2(f,prefix/'bin'/name)
 if not os.access(prefix/'bin'/name,os.X_OK):raise RuntimeError('Copied ELF not executable '+name)
 sha[name]=hashlib.sha256((prefix/'bin'/name).read_bytes()).hexdigest()
for name in ['LICENSE','LICENSE.Apache-2.0','LICENSING.md','README.md']:
 shutil.copy2(source/name,prefix/'share/doc/aflplusplus'/name)
print(json.dumps({'status':'passed','scope':'six native reduced-mode binaries, no LLVM instrumentation, no full distrib',
 'seconds':round(time.monotonic()-started,2),'source':str(source),
 'prefix':str(prefix),'binary_sha256':sha},sort_keys=True))
