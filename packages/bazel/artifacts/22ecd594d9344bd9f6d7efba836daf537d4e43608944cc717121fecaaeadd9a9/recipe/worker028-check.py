#!/usr/bin/env python3
"""Replay the concrete worker028 acceptance cases; no network acquisition."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


class Check:
    def __init__(self, args):
        self.args = args
        self.prefix = args.prefix.resolve()
        args.build.resolve().mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix='worker028-'+args.case+'-',dir=args.build.resolve()))
        self.logs = self.work / 'logs'
        self.logs.mkdir()
        self.steps = []
        self.assertions = []

    def require(self, condition, description):
        self.assertions.append({'description': description, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(description)

    def run(self, argv, *, cwd=None, expected=(0,), env=None, timeout=180):
        argv = [str(x) for x in argv]
        directory = Path(cwd or self.work)
        start = time.monotonic()
        process = subprocess.Popen(argv, cwd=directory, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout,stderr=process.communicate()
        r=subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)
        stem = f'{len(self.steps)+1:03d}'
        (self.logs / (stem + '.stdout.txt')).write_text(r.stdout)
        (self.logs / (stem + '.stderr.txt')).write_text(r.stderr)
        self.steps.append({'argv': argv, 'cwd': str(directory), 'returncode': r.returncode,
                           'seconds': time.monotonic()-start,
                           'stdout': 'logs/'+stem+'.stdout.txt', 'stderr': 'logs/'+stem+'.stderr.txt',
                           'runtime_bindings': {k:(env or os.environ)[k] for k in ['PATH','LD_LIBRARY_PATH','CPG_CLANGXX'] if k in (env or os.environ)},
                           'timed_out':timed_out,
                           'expected_returncodes': list(expected) if expected is not None else None})
        (self.logs / (stem + '.command.json')).write_text(json.dumps(self.steps[-1], indent=2)+'\n')
        if timed_out:
            raise TimeoutError(f'{argv[0]} exceeded {timeout}s; its process group was terminated and partial output retained')
        if expected is not None and r.returncode not in expected:
            raise RuntimeError(f'{argv[0]} returned {r.returncode}: {r.stderr[-3500:]}')
        return r

    def put(self, name, text):
        p = self.work / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def compiledb(self):
        self.put('include space/config.h', '#define CONFIG 7\n')
        self.put('src space/a file.c', '#include "config.h"\nint a(void){return CONFIG;}\n')
        sub = self.work / 'nested dir'
        self.put('nested dir/b.cc', 'int b(){return 3;}\n')
        sentinel = self.work / 'LOG_COMMAND_WAS_EXECUTED'
        fake = self.put('fake-compiler/gcc', '#!/bin/sh\ntouch '+shlex.quote(str(sentinel))+'\nexit 97\n')
        fake.chmod(0o755)
        log = self.put('build.log', '\n'.join([
            f"make: Entering directory '{self.work}'",
            f"{shlex.quote(str(fake))} '-DMSG=hello world' -I'include space' -c 'src space/a file.c' -o a.o",
            f'touch {shlex.quote(str(sentinel))}',
            f"make[1]: Entering directory '{sub}'",
            'c++ -std=c++17 -DNUMBER=3 -c b.cc -o b.o',
            f"make[1]: Leaving directory '{sub}'",
            f"make: Leaving directory '{self.work}'", '']))
        tool = self.prefix/'bin/compiledb'
        self.run([tool,'--parse',log,'--build-dir',self.work,'--output',self.work/'compile_commands.json','--overwrite'])
        rows = json.loads((self.work/'compile_commands.json').read_text())
        self.require(len(rows)==2, 'two translation units parsed from stored log')
        a = next(r for r in rows if Path(r['file']).name=='a file.c')
        b = next(r for r in rows if Path(r['file']).name=='b.cc')
        self.require(Path(a['directory']).resolve()==self.work, 'first compile working directory preserved')
        self.require(Path(b['directory']).resolve()==sub, 'nested make working directory preserved')
        self.require('-DMSG=hello world' in a['arguments'], 'quoted argument containing spaces is one exact argument')
        self.require('-Iinclude space' in a['arguments'], 'quoted include-directory argument is unescaped exactly once')
        self.require('src space/a file.c' in a['arguments'], 'source filename with spaces is one argument')
        self.require(not sentinel.exists(), 'neither logged shell command nor fake compiler was executed')
        self.require(not (self.work/'a.o').exists() and not (sub/'b.o').exists(), 'log parsing creates no compilation outputs')
        self.run([tool,'--parse',log,'--build-dir',self.work,'--output',self.work/'command-style.json','--overwrite','--command-style'])
        command_rows = json.loads((self.work/'command-style.json').read_text())
        ca = next(r for r in command_rows if Path(r['file']).name=='a file.c')
        roundtrip=shlex.split(ca['command'])==a['arguments']
        self.put('known-limitations.json',json.dumps({'command_style_preserves_space_quoting':roundtrip,'supported_export':'arguments array','guidance':'compiledb 0.10.7 --command-style joins arguments without preserving shell quoting; retain the default arguments array for paths and flags with spaces.'},indent=2)+'\n')
        self.require(not roundtrip, 'known upstream command-style quoting loss is detected; only the exact arguments-array form is qualified')

    def sphinx(self):
        self.put('docs/tinycompiler.py', 'def fold_add(a, b):\n    """Fold two integer literals.\n\n    >>> fold_add(19, 23)\n    42\n    """\n    return a+b\n')
        self.put('docs/conf.py', "import os,sys\nsys.path.insert(0,os.path.abspath('.'))\nproject='CPG worker028 API'\nextensions=['sphinx.ext.autodoc','sphinx.ext.doctest']\nmaster_doc='index'\nhtml_theme='alabaster'\nnitpicky=True\nexclude_patterns=[]\ndoctest_global_setup='from tinycompiler import fold_add'\n")
        self.put('docs/index.rst', 'Compiler API\n============\n\n.. toctree::\n\n   api\n\nThe :py:func:`tinycompiler.fold_add` function is documented in :ref:`api-index`.\n\n.. code-block:: python\n\n   fold_add(19, 23)\n\n.. doctest::\n\n   >>> from tinycompiler import fold_add\n   >>> fold_add(20, 22)\n   42\n')
        self.put('docs/api.rst', '.. _api-index:\n\nAPI reference\n=============\n\n.. automodule:: tinycompiler\n   :members:\n')
        tool = self.prefix/'bin/sphinx-build'
        self.run([tool,'-W','-n','-b','html',self.work/'docs',self.work/'html'])
        index=(self.work/'html/index.html').read_text()
        api=(self.work/'html/api.html').read_text()
        self.require('api.html#tinycompiler.fold_add' in index, 'HTML function cross-reference resolves to generated API anchor')
        self.require('api.html#api-index' in index, 'explicit documentation label resolves')
        self.require('id="tinycompiler.fold_add"' in api, 'autodoc creates function anchor from real Python module')
        self.require('fold_add' in index and '23' in index and 'highlight-python' in index, 'HTML contains the documented code example')
        self.require((self.work/'html/objects.inv').stat().st_size>100, 'offline inventory is generated')
        self.run([tool,'-W','-b','doctest',self.work/'docs',self.work/'doctest'])
        result=(self.work/'doctest/output.txt').read_text()
        self.require('0 failures in tests' in result, 'documented Python examples execute without failures')
        rst=self.work/'docs/index.rst'; original=rst.read_text()
        rst.write_text(original.replace('   42\n','   43\n'))
        failed=self.run([tool,'-E','-W','-b','doctest',self.work/'docs',self.work/'bad-doctest'],expected=None)
        self.require(failed.returncode!=0, 'incorrect documented expected value is rejected')
        rst.write_text(original+'\nBroken reference :py:func:`tinycompiler.missing_function`.\n')
        missing=self.run([tool,'-E','-W','-n','-b','html',self.work/'docs',self.work/'bad-html'],expected=None)
        self.require(missing.returncode!=0 and 'missing_function' in missing.stderr, 'broken API cross-reference fails warnings-as-errors build')
        rst.write_text(original)

    def doxygen(self):
        self.put('api.h', '''/** @file api.h */
#pragma once
/** Compiler IR namespace. */
namespace cpg {
/** Operation code. */
enum class Opcode { Add, Multiply };
/** An integer IR value. */
struct Value { int integer; };
/** Fold two constant values. @return folded integer. */
Value fold_add(Value lhs, Value rhs);
/** Uses @ref fold_add to simplify integer IR. */
class AddPass {
public:
  /** Apply @ref fold_add. */
  Value run(Value lhs, Value rhs);
};
}
''')
        cfg=self.put('Doxyfile', 'PROJECT_NAME = "CPG IR fixture"\nOUTPUT_DIRECTORY = out\nINPUT = api.h\nFILE_PATTERNS = *.h\nRECURSIVE = NO\nEXTRACT_ALL = YES\nGENERATE_XML = YES\nGENERATE_HTML = NO\nGENERATE_LATEX = NO\nHAVE_DOT = NO\nQUIET = YES\nWARN_AS_ERROR = YES\nWARN_IF_UNDOCUMENTED = NO\nFULL_PATH_NAMES = NO\n')
        self.run([self.prefix/'bin/doxygen',cfg])
        xml=self.work/'out/xml'; index=ET.parse(xml/'index.xml').getroot()
        names={e.findtext('name') for e in index.findall('compound')}
        self.require({'cpg','cpg::Value','cpg::AddPass'}.issubset(names), 'XML index exposes namespace and two C++ types')
        files=[ET.parse(p).getroot() for p in xml.glob('*.xml') if p.name!='index.xml']
        members=[m for root in files for m in root.findall('.//memberdef')]
        self.require(any(m.get('kind')=='function' and m.findtext('name')=='fold_add' for m in members), 'fold_add is a function entry')
        self.require(any(m.get('kind')=='function' and m.findtext('name')=='run' for m in members), 'AddPass::run is indexed as a function')
        self.require(any(m.get('kind')=='enum' and m.findtext('name')=='Opcode' for m in members), 'Opcode is an enum entry')
        ids={e.get('id') for root in files for e in root.iter() if e.get('id')}
        self.require(any(ref.text=='fold_add' and ref.get('refid') in ids for root in files for ref in root.findall('.//ref')), 'documentation function cross-reference resolves to an existing XML member id')
        self.require(any(ref.text=='Value' and ref.get('refid') in ids for m in members for ref in m.findall('./type/ref')), 'return type references resolve to an existing Value compound')

    def iwyu(self):
        self.put('indirect.h', '#pragma once\n#include <vector>\n')
        src=self.put('example.cc', '#include "indirect.h"\n#include <set>\nint main(){std::vector<int> v{19,23};return v.size()==2 ? 0 : 1;}\n')
        tool=self.prefix/'bin/include-what-you-use'
        v=self.run([tool,'--version'])
        self.require('0.21' in v.stdout and '17.0.6' in v.stdout, 'IWYU release and linked Clang match the locked 0.21 / 17.0.6 pair')
        args=[tool,'-std=c++17','-I',self.work,'-Xiwyu','--no_fwd_decls','-c',src]
        before=self.run(args)
        text=before.stdout+before.stderr
        self.require('#include <vector>' in text and 'should add these lines' in text, 'transitive vector use yields direct include suggestion')
        self.require('should remove these lines' in text and '#include <set>' in text, 'unused set include is diagnosed')
        self.put('fixed.cc', '#include <vector>\nint main(){std::vector<int> v{19,23};return v.size()==2 ? 0 : 1;}\n')
        self.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',self.work/'fixed.cc','-o',self.work/'fixed'])
        self.run([self.work/'fixed'])
        after=self.run([tool,'-std=c++17','-Xiwyu','--no_fwd_decls','-c',self.work/'fixed.cc'])
        at=after.stdout+after.stderr
        self.require('correct #includes/fwd-decls' in at and 'should add these lines' not in at, 'applied include repair is accepted by IWYU')

    def bloaty(self):
        src=self.put('size_fixture.c', '#ifndef PAD\n#define PAD 64\n#endif\n#ifndef BLOB\n#define BLOB 64\n#endif\n#define STR2(x) #x\n#define STR(x) STR2(x)\nvolatile unsigned char cpg_blob[BLOB]={1};\n__attribute__((noinline)) int unchanged(void){return 7;}\n__attribute__((noinline)) int grown_function(int x){__asm__ volatile(".rept " STR(PAD) "\\n nop\\n .endr");return x+cpg_blob[0];}\n')
        for name,pad,blob in [('base',64,64),('grown',512,1024)]:
            self.run(['gcc','-g','-gdwarf-4','-O0','-fno-inline','-ffunction-sections','-fdata-sections',f'-DPAD={pad}',f'-DBLOB={blob}','-c',src,'-o',self.work/(name+'.o')])
        tool=self.prefix/'bin/bloaty'
        syms=self.run([tool,'--csv','-d','symbols',self.work/'grown.o','--',self.work/'base.o'])
        rows=list(csv.DictReader(io.StringIO(syms.stdout)))
        mapping={r['symbols']:r for r in rows}
        self.require('grown_function' in mapping and 'cpg_blob' in mapping, 'DWARF/symbol diff exposes both controlled growth symbols')
        self.require(int(mapping['grown_function']['vmsize'])==448, 'function VM growth equals the 448 added one-byte instructions')
        self.require(int(mapping['cpg_blob']['vmsize'])==960, 'data-symbol VM growth equals 1024 minus 64 bytes')
        self.require('unchanged' not in mapping or int(mapping['unchanged']['vmsize'])==0, 'unchanged function has no VM-size growth')
        sections=self.run([tool,'--csv','-d','sections',self.work/'grown.o','--',self.work/'base.o'])
        sr=list(csv.DictReader(io.StringIO(sections.stdout)))
        sm={r['sections']:r for r in sr}
        self.require(int(sm['.text.grown_function']['vmsize'])==448, 'text section growth matches changed function')
        self.require(int(sm['.data.cpg_blob']['vmsize'])==960, 'data section growth matches controlled array')
        object_cu=self.run([tool,'--csv','-d','compileunits',self.work/'grown.o'],expected=None)
        self.require(object_cu.returncode!=0 and "can't use data source 'compileunits' on object files" in object_cu.stderr, 'upstream limitation for compileunits on relocatable objects is explicitly detected')
        driver=self.put('driver.c','int grown_function(int);int unchanged(void);int main(void){return grown_function(0)+unchanged();}\n')
        self.run(['gcc','-g','-gdwarf-4','-O0',driver,self.work/'grown.o','-o',self.work/'grown.elf'])
        cu=self.run([tool,'--csv','-d','compileunits',self.work/'grown.elf'])
        self.require('size_fixture.c' in cu.stdout, 'DWARF compile-unit attribution works on the linked executable')
        self.run(['readelf','--debug-dump=info',self.work/'grown.o'])

    def clang_build_analyzer(self):
        trace=self.work/'trace';trace.mkdir()
        self.put('trace/one.cc','#include <vector>\nint cpg_one(){std::vector<int> x{1,2,3};int s=0;for(int v:x)s+=v;return s;}\n')
        self.put('trace/two.cc','#include <string>\nint cpg_two(){std::string s="cpg trace";return static_cast<int>(s.size());}\n')
        tool=self.prefix/'bin/ClangBuildAnalyzer'
        clang=os.environ.get('CPG_CLANGXX') or shutil.which('clang++-17') or shutil.which('clang++')
        self.require(bool(clang), 'a real Clang compiler is explicitly available')
        self.run([clang,'--version'])
        self.run([tool,'--start',trace])
        for stem in ['one','two']:
            self.run([clang,'-std=c++17','-O1','-ftime-trace','-ftime-trace-granularity=0','-c',trace/(stem+'.cc'),'-o',trace/(stem+'.o')])
        traces=sorted(trace.glob('*.json'))
        self.require(len(traces)==2, 'two actual compiler trace JSON files were generated')
        for f in traces:
            events=json.loads(f.read_text())['traceEvents']
            self.require(any(e.get('name')=='ExecuteCompiler' and e.get('dur',0)>0 for e in events), f'{f.name} has a positive real compiler duration')
        self.run([tool,'--stop',trace,self.work/'capture.bin'])
        report=self.run([tool,'--analyze',self.work/'capture.bin'])
        self.require('Compilation (2 times)' in report.stdout, 'analyzer aggregates exactly two real translation-unit traces')
        self.require('frontend' in report.stdout and 'backend' in report.stdout, 'analyzer reports frontend and backend costs')
        self.require('one.o' in report.stdout and 'two.o' in report.stdout, 'analysis retains both output-file identities')
        bad=self.put('bad-capture.bin','not a ClangBuildAnalyzer capture')
        rejected=self.run([tool,'--analyze',bad],expected=None)
        self.require(rejected.returncode!=0, 'invalid analyzer capture is rejected')

    def bear(self):
        root=self.args.support.resolve()
        self.put('project/include space/config.h','#define CPG_VALUE 42\n')
        self.put('project/src space/answer.c','#include "config.h"\nint answer(void){return CPG_VALUE;}\n')
        self.put('project/main.c','int answer(void);int main(void){return answer()==42?0:1;}\n')
        self.put('project/compile.rsp','-I"include space" -c "src space/answer.c" -o answer.o\n')
        script=self.put('build.py', 'import subprocess\nfrom pathlib import Path\np=Path(__file__).parent/"project"\nfor a in [["gcc","@compile.rsp"],["gcc","-c","main.c","-o","main.o"],["gcc","answer.o","main.o","-o","app"]]:\n subprocess.run(a,cwd=p,check=True)\nsubprocess.run([str(p/"app")],check=True)\n')
        env=os.environ.copy();env['LD_LIBRARY_PATH']=str(root/'usr/lib/x86_64-linux-gnu')
        bear=root/'usr/bin/bear';lib=root/'usr/lib/x86_64-linux-gnu/bear'
        self.run([bear,'--bear-path',bear,'--library',lib/'libexec.so','--wrapper',lib/'wrapper','--wrapper-dir',lib/'wrapper.d','--output',self.work/'compile_commands.json','--','python3',script],env=env)
        rsp_rows=json.loads((self.work/'compile_commands.json').read_text())
        self.require((self.work/'project/answer.o').stat().st_size>0, 'response-file compile really ran successfully')
        self.require(len(rsp_rows)==1 and Path(rsp_rows[0]['file']).name=='main.c', 'Bear 3.1.3 response-file omission is reproduced and not silently treated as a complete database')
        self.put('known-limitations.json',json.dumps({'bear_version':'3.1.3-1build4','response_file_compile_ran':True,'response_file_compile_captured':False,'guidance':'This locked Bear build omits the GCC @response-file compile from citnames output. Use direct compiler arguments or explicitly expand response files before interception; do not treat this database as complete for such builds.'},indent=2)+'\n')
        direct=self.put('build-direct.py', 'import subprocess\nfrom pathlib import Path\np=Path(__file__).parent/"project"\nfor a in [["gcc","-Iinclude space","-c","src space/answer.c","-o","answer.o"],["gcc","-c","main.c","-o","main.o"],["gcc","answer.o","main.o","-o","app"]]:\n subprocess.run(a,cwd=p,check=True)\nsubprocess.run([str(p/"app")],check=True)\n')
        self.run([bear,'--bear-path',bear,'--library',lib/'libexec.so','--wrapper',lib/'wrapper','--wrapper-dir',lib/'wrapper.d','--output',self.work/'compile_commands-direct.json','--','python3',direct],env=env)
        rows=json.loads((self.work/'compile_commands-direct.json').read_text())
        self.require(len(rows)==2,'Bear captures two compile translation units and excludes the link invocation')
        self.require(all(Path(r['directory']).resolve()==self.work/'project' for r in rows),'Bear records actual nested working directory for both compiler invocations')
        self.require({Path(r['file']).name for r in rows}=={'answer.c','main.c'},'both direct-argument sources, including a spaced path, are identified')
        for i,r in enumerate(rows):
            argv=list(r['arguments'])
            if '-o' in argv: argv[argv.index('-o')+1]=str(self.work/f'replayed-{i}.o')
            self.run(argv,cwd=r['directory'])
        self.require(all((self.work/f'replayed-{i}.o').stat().st_size>0 for i in range(2)),'both captured argument vectors replay into actual object files')

    def bazel(self):
        fixture=self.prefix/'share/bazel/fixture'
        archive_path=self.prefix/'share/bazel/fixture.tar.gz'
        project=self.work/'project'
        if archive_path.is_file():
            declared=json.loads((archive_path.parent/'fixture-lock.json').read_text())
            self.require(archive_path.stat().st_size==declared['bytes'], 'Bazel fixture archive byte count matches its explicit lock')
            self.require(sha(archive_path)==declared['sha256'], 'Bazel fixture archive SHA256 matches its explicit lock')
            project.mkdir()
            with tarfile.open(archive_path) as archive:
                archive.extractall(project,filter='data')
        elif fixture.is_dir():
            shutil.copytree(fixture,project,symlinks=True)
        else:
            raise FileNotFoundError('Neither the locked Bazel fixture archive nor a complete fixture tree is available')
        required=['host-toolchain-lock.json','MODULE.bazel','MODULE.bazel.lock','BUILD.bazel','sum.c','sum.h','main.cc','test.cc']
        self.require(all((project/name).is_file() for name in required) and (project/'vendor/_registries').is_dir(), 'Restored fixture contains all locked project inputs and the vendored registry')
        lock=json.loads((project/'host-toolchain-lock.json').read_text())
        for entry in lock['files']:
            self.require(Path(entry['path']).is_file() and sha(entry['path'])==entry['sha256'], 'toolchain input matches pinned bytes: '+entry['path'])
        before=sha(project/'MODULE.bazel.lock')
        tool=self.prefix/'bin/bazel'
        startup=[tool,'--batch','--output_user_root='+str(self.work/'output')]
        common=['--vendor_dir=vendor','--lockfile_mode=error','--repository_cache='+str(self.work/'empty-cache'),'--jobs=2','--local_resources=cpu=2','--spawn_strategy=standalone','--strategy=TestRunner=standalone']
        self.run(startup+['test']+common+['--test_output=all','//...'],cwd=project,timeout=600)
        app=project/'bazel-bin/cpp_main'
        initial=self.run([app],cwd=project)
        self.require(initial.stdout.strip()=='CPG=42','offline C/C++ executable links and computes the expected result')
        self.run(startup+['clean'],cwd=project,timeout=180)
        self.run(startup+['test']+common+['--test_output=all','//...'],cwd=project,timeout=600)
        self.require(self.run([app],cwd=project).stdout.strip()=='CPG=42','clean rebuild succeeds offline with preserved result')
        source=project/'sum.c'; original=source.read_text();source.write_text(original.replace('return x + y;','return x + y + 1;'))
        failure=self.run(startup+['test']+common+['--test_output=all','//...'],cwd=project,timeout=600,expected=None)
        self.require(failure.returncode!=0,'source mutation invalidates build cache and fails the known-answer test')
        self.require(self.run([app],cwd=project).stdout.strip()=='CPG=43','rebuilt executable reflects the intentional source mutation')
        source.write_text(original)
        self.run(startup+['test']+common+['--test_output=all','//...'],cwd=project,timeout=600)
        self.require(sha(project/'MODULE.bazel.lock')==before,'all builds retain the exact Bzlmod lockfile')

    def execute(self):
        status='failed'; error=None
        try:
            if self.args.case!='bear':
                for family in (socket.AF_INET,socket.AF_INET6):
                    try:
                        with socket.socket(family,socket.SOCK_STREAM):
                            blocked=False
                    except OSError:
                        blocked=True
                    self.require(blocked,f'network guard denies creation of {family.name} sockets')
            getattr(self,self.args.case.replace('-','_'))()
            status='passed'
        except Exception as e:
            error=type(e).__name__+': '+str(e)
        result={'schema_version':1,'case':self.args.case,'status':status,'prefix':str(self.prefix),
                'work':str(self.work),'assertions':self.assertions,'steps':self.steps,'error':error,
                'scope':'Bounded native fixture qualification; not OCI, all upstream inputs, or physical target qualification.'}
        (self.work/'check-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'case':self.args.case,'status':status,'assertion_count':len(self.assertions),'evidence':str(self.work/'check-summary.json'),'error':error},ensure_ascii=False))
        return 0 if status=='passed' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,choices=['compiledb','sphinx','doxygen','iwyu','bloaty','clang-build-analyzer','bear','bazel'])
    parser.add_argument('--prefix',required=True,type=Path)
    parser.add_argument('--build',required=True,type=Path)
    parser.add_argument('--support',type=Path)
    args=parser.parse_args()
    return Check(args).execute()


if __name__=='__main__':
    raise SystemExit(main())
