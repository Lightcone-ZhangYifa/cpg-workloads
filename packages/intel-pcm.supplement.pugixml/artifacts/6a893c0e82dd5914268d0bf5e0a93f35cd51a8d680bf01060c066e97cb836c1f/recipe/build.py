#!/usr/bin/env python3
"""Compile pinned pugixml and run its complete standard-profile test executable."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

RESOURCE='intel-pcm.supplement.pugixml'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','build','prefix'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--jobs',type=int,required=True);args=p.parse_args()
    if not 1<=args.jobs<=2:raise RuntimeError('At most two compiler jobs are permitted')
    source=args.source.resolve();build=args.build/'pugixml';prefix=args.prefix.resolve()
    if build.exists():raise RuntimeError('Fresh build required')
    shutil.copytree(source,build,symlinks=True)
    recipe=Path(__file__).resolve().parent
    config=json.loads((recipe/'config.json').read_text())
    evidence=prefix/'share/compiler-playground'/RESOURCE;evidence.mkdir(parents=True)
    for path in ('include','lib','bin'): (prefix/path).mkdir(parents=True,exist_ok=True)
    environment=dict(os.environ,LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
    for key in ('LD_PRELOAD','LD_LIBRARY_PATH','LIBRARY_PATH','CPATH','CPLUS_INCLUDE_PATH','C_INCLUDE_PATH',
                'CXXFLAGS','CPPFLAGS','CFLAGS','LDFLAGS','MAKEFLAGS','MFLAGS'):
        environment.pop(key,None)
    commands=[]
    def run(label,argv,timeout=900):
        argv=list(map(str,argv))
        print(json.dumps({'label':label,'argv':argv}),flush=True)
        with (evidence/(label+'.stdout')).open('w') as out,(evidence/(label+'.stderr')).open('w') as err:
            cp=subprocess.run(argv,cwd=build,env=environment,stdout=out,stderr=err,text=True,timeout=timeout)
        commands.append({'label':label,'argv':argv,'cwd':str(build),'returncode':cp.returncode,
                         'stdout':label+'.stdout','stderr':label+'.stderr'})
        (evidence/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if cp.returncode:raise RuntimeError('Real build/test command failed: '+label)
        return (evidence/(label+'.stdout')).read_text()

    flags=config['compiler_flags']
    obj=build/'pugixml-library.o'
    run('compile-library',['/usr/bin/g++',*flags,'-fPIC','-c',source/'src/pugixml.cpp','-o',obj])
    run('archive-library',['/usr/bin/ar','rcsD',prefix/'lib/libpugixml.a',obj],120)
    run('link-library',['/usr/bin/g++','-shared','-Wl,-soname,libpugixml.so.1','-Wl,-z,defs',obj,
                        '-o',prefix/'lib/libpugixml.so.1.15'],120)
    (prefix/'lib/libpugixml.so.1').symlink_to('libpugixml.so.1.15')
    (prefix/'lib/libpugixml.so').symlink_to('libpugixml.so.1')
    for name in ('pugixml.hpp','pugiconfig.hpp'):shutil.copy2(source/'src'/name,prefix/'include'/name)

    # This declared observation-only build-copy patch emits a pass only after
    # the original run_test checks/assertions/leak checks have returned true.
    # The complete original source view remains byte-for-byte unchanged.
    main_file=build/'tests/main.cpp'
    original=main_file.read_text()
    if sha(main_file)!=config['upstream_main_sha256']:raise RuntimeError('Pinned harness identity differs')
    start='static bool run_test(test_runner* test, const char* test_name, pugi::allocation_function allocate)\n{\n'
    end='\t\treturn true;\n'
    if original.count(start)!=1 or original.count(end)!=1:raise RuntimeError('Observer patch anchors are not unique')
    observed=original.replace(start,start+'\tprintf("CPG_UPSTREAM_BEGIN %s\\n", test_name);\n')
    observed=observed.replace(end,'\t\tprintf("CPG_UPSTREAM_PASS %s\\n", test_name);\n'+end)
    main_file.write_text(observed)
    patch={'file':'tests/main.cpp','original_sha256':hashlib.sha256(original.encode()).hexdigest(),
           'observed_sha256':sha(main_file),'purpose':'Two printf observations; no assertion, selector, return or test logic changed',
           'recipe_sha256':sha(recipe/'build.py')}
    (evidence/'harness-observation-patch.json').write_text(json.dumps(patch,indent=2)+'\n')
    (evidence/'upstream-main-observed.cpp').write_text(observed)
    test_sources=[source/'src/pugixml.cpp',*[x for x in sorted((source/'tests').glob('*.cpp')) if not x.name.startswith('fuzz_')]]
    source_rows=[{'path':x.relative_to(source).as_posix(),'sha256':sha(x),'bytes':x.stat().st_size} for x in test_sources]
    (evidence/'upstream-test-translation-units.json').write_text(json.dumps(source_rows,indent=2)+'\n')
    upstream_build=build/'compiled-upstream-tests'
    make=['/usr/bin/make','-j'+str(args.jobs),'CXX=/usr/bin/g++','config=debug','defines=standard',
          'cxxstd=c++17','BUILD='+str(upstream_build),'CXXFLAGS='+' '.join(config['upstream_test_compiler_flags']),
          'LDFLAGS=']
    run('build-upstream-tests',make+['all'])
    stdout=run('run-upstream-tests',[upstream_build/'test'],300)
    begins=re.findall(r'^CPG_UPSTREAM_BEGIN (.+)$',stdout,re.M)
    passes=re.findall(r'^CPG_UPSTREAM_PASS (.+)$',stdout,re.M)
    summaries=re.findall(r'^Success: (\d+) tests passed\.$',stdout,re.M)
    if len(summaries)!=1 or not begins or begins!=passes or len(passes)!=int(summaries[0]):
        raise RuntimeError('Actual upstream execution was empty, incomplete or inconsistent')
    if re.search(r'^FAILURE:|^Test .+ failed',stdout,re.M):raise RuntimeError('Upstream reported a failed case')
    if any(n!=1 for n in Counter(begins).values()):raise RuntimeError('Duplicate actual case invocation identity')
    base_names=[name for name in begins if not name.endswith(' (throw)')]
    throw_names=[name for name in begins if name.endswith(' (throw)')]
    if not all(name[:-8] in base_names for name in throw_names):raise RuntimeError('Unmatched allocator throw repeat')
    upstream={'status':'passed','profile':'Complete upstream Makefile standard C++17 debug/assertions test executable; optional fuzz/sanitizer/alternate-define matrices are separate',
              'test_executables':1,'translation_units':source_rows,'executed_case_invocations':len(begins),
              'base_test_cases':len(base_names),'allocator_throw_repeats':len(throw_names),'failed':0,'skipped':0,
              'case_invocations':[{'name':name,'status':'passed','allocator_throw_repeat':name.endswith(' (throw)')} for name in begins],
              'stdout_sha256':sha(evidence/'run-upstream-tests.stdout'),
              'test_executable_sha256':sha(upstream_build/'test'),'harness_observation_patch':patch}
    shutil.copytree(source,prefix/'share'/RESOURCE/'source',symlinks=True)
    shutil.copy2(source/'LICENSE.md',prefix/'share'/RESOURCE/'LICENSE.md')
    for name in ('build.py','check.py','consumer.cpp','config.json'):shutil.copy2(recipe/name,evidence/name)
    run('build-probe',['/usr/bin/g++',*flags,'-I'+str(prefix/'include'),recipe/'consumer.cpp',prefix/'lib/libpugixml.so',
                       '-Wl,-rpath,$ORIGIN/../lib','-o',prefix/'bin/pugixml-cpg-probe'],120)
    tool_observations=[]
    for command in ('/usr/bin/g++','/usr/bin/ar','/usr/bin/make'):
        real=Path(command).resolve(strict=True)
        observed_version=run('tool-'+Path(command).name.replace('+','x'),[command,'--version'],30)
        tool_observations.append({'command':command,'realpath':str(real),'sha256':sha(real),'bytes':real.stat().st_size,'version_output':observed_version})
    profile={'schema_version':1,'id':RESOURCE,'catalog_version':'202604','library_version':'1.15','header_version':1150,
             'configuration':config['configuration'],'compiler_flags':flags,'actual_jobs':args.jobs,'maximum_jobs':2,
             'source_modified':False,'build_copy_test_observation_patch':patch,'upstream_tests':upstream,
             'observed_build_tools':tool_observations,'unperformed':config['unperformed'],
             'relocation_scope':'Explicit-prefix C++ consumers and project probe on the observed Ubuntu 24.04 x86_64 libstdc++/glibc ABI; headers/static/shared libraries and full original source are retained.'}
    (evidence/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')

if __name__=='__main__':main()
