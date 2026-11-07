#!/usr/bin/env python3
"""Bounded, offline, non-mocked acceptance checks for CPG worker 029.

Every command records argv, cwd, return code, stdout and stderr.  The optional
network service is Buildbot, bound to loopback, and all its child processes are
stopped before this checker exits. BenchExec never substitutes ulimit for cgroups.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class Check:
    def __init__(self, prefix, output):
        self.prefix = Path(prefix).resolve()
        self.out = Path(output).resolve()
        if self.out.exists() and any(self.out.iterdir()):
            self.out = self.out / ('run-' + str(time.time_ns()))
        self.out.mkdir(parents=True, exist_ok=True)
        self.commands = []
        self.assertions = []

    def run(self, argv, name, expected=None, cwd=None, env=None, timeout=90):
        argv = list(map(str, argv))
        start = time.monotonic()
        proc = subprocess.Popen(argv, cwd=cwd or self.out, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            write(self.out / (name + '.stdout'), stdout)
            write(self.out / (name + '.stderr'), stderr)
            raise
        p = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
        write(self.out / (name + '.stdout'), p.stdout)
        write(self.out / (name + '.stderr'), p.stderr)
        self.commands.append({'name': name, 'argv': argv,
                              'cwd': str(cwd or self.out),
                              'returncode': p.returncode,
                              'seconds': time.monotonic() - start,
                              'stdout': name + '.stdout', 'stderr': name + '.stderr'})
        if expected is not None:
            self.require(p.returncode == expected,
                         f'{name}: exit {p.returncode}, expected {expected}')
        return p

    def require(self, ok, description):
        self.assertions.append({'passed': bool(ok), 'assertion': description})
        if not ok:
            raise AssertionError(description)


GOOD = '''name: Valid CPG workflow
on: push
permissions: {}
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Check constant
        run: test 42 -eq 42
'''
BAD = '''name: Invalid CPG workflow
on: push
permissions: {}
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Invalid context property
        run: echo "${{ github.nonexistent_property }}"
'''
UNSAFE = '''name: Unsafe interpolation fixture
on: pull_request
permissions: {}
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Unsafe interpolation
        run: echo "${{ github.event.pull_request.title }}"
'''


def actionlint(c):
    good = write(c.out / 'good.yml', GOOD)
    bad = write(c.out / 'bad.yml', BAD)
    exe = c.prefix / 'bin/actionlint'
    cmd = [exe, '-no-color', '-shellcheck=', '-pyflakes=']
    c.run(cmd + [good], 'valid-workflow', 0)
    p = c.run(cmd + [bad], 'invalid-workflow', 1)
    c.require('bad.yml:9:24:' in p.stdout, 'expression diagnostic is at line 9, column 24')
    c.require('nonexistent_property' in p.stdout and '[expression]' in p.stdout,
              'unknown GitHub context property is rejected by the expression rule')
    return {'scope': 'workflow syntax/type/expression checks; optional shellcheck/pyflakes disabled explicitly'}


def zizmor(c):
    exe = c.prefix / 'bin/zizmor'
    good = write(c.out / 'good.yml', GOOD)
    unsafe = write(c.out / 'unsafe.yml', UNSAFE)
    gp = c.run([exe, '--offline', '--format', 'sarif', good], 'valid-sarif', 0)
    bad = c.run([exe, '--offline', '--format', 'sarif', unsafe], 'unsafe-sarif')
    g = json.loads(gp.stdout); b = json.loads(bad.stdout)
    c.require(g['runs'][0]['results'] == [], 'safe fixture has no SARIF findings')
    findings = [r for r in b['runs'][0]['results'] if r['ruleId'] == 'zizmor/template-injection']
    c.require(len(findings) == 1, 'unsafe interpolation emits exactly one template-injection finding')
    loc = findings[0]['locations'][0]['physicalLocation']['region']
    c.require(loc['startLine'] == 9 and loc['startColumn'] == 24,
              'SARIF finding points to attacker-controlled interpolation at 9:24')
    write(c.out / 'unsafe.sarif.json', json.dumps(b, indent=2) + '\n')
    return {'scope': 'offline local workflow audit; no GitHub API or remote repository access',
            'unsafe_exit_code': bad.returncode}


def buildbot(c):
    exe = c.prefix / 'bin/buildbot'
    workerexe = c.prefix / 'bin/buildbot-worker'
    master, worker = c.out / 'master', c.out / 'worker'
    c.require(not master.exists() and not worker.exists(), 'fresh independent master and worker directories')
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    c.run([exe, 'create-master', master], 'create-master', 0)
    fixture = write(c.out / 'compile_and_test.py', '''import pathlib, subprocess
p=pathlib.Path('answer.c')
p.write_text('#include <stdio.h>\\nint main(void){printf("%d\\\\n",6*7);return 0;}\\n')
subprocess.run(['gcc','-O2','-Wall','-Werror','answer.c','-o','answer'],check=True)
r=subprocess.check_output(['./answer'],text=True).strip()
assert r=='42',r
pathlib.Path('result.json').write_text('{"compiled":true,"actual":42,"expected":42}\\n')
print('CPG_BUILD_AND_TEST_OK actual=42 expected=42',flush=True)
''')
    config = f'''from buildbot.plugins import worker, schedulers, util, steps
BuildmasterConfig = c = {{}}
c['workers'] = [worker.Worker('isolated-local-worker', 'local-test-only')]
c['protocols'] = {{'pb': {{'port': 'tcp:{port}:interface=127.0.0.1'}}}}
c['schedulers'] = [schedulers.Periodic(name='local-only', builderNames=['compile-test'], periodicBuildTimer=8)]
c['buildbotNetUsageData'] = None
f=util.BuildFactory()
f.addStep(steps.ShellCommand(name='compile-and-test', command=[{sys.executable!r}, {str(fixture)!r}], haltOnFailure=True, logEnviron=False))
c['builders'] = [util.BuilderConfig(name='compile-test', workernames=['isolated-local-worker'], factory=f)]
c['title']='CPG isolated acceptance'
c['titleURL']='http://127.0.0.1/'
c['buildbotURL']='http://127.0.0.1/'
c['db']={{'db_url':'sqlite:///state.sqlite'}}
'''
    write(master / 'master.cfg', config)
    c.run([exe, 'checkconfig', master], 'checkconfig', 0)
    c.run([workerexe, 'create-worker', worker, f'127.0.0.1:{port}',
           'isolated-local-worker', 'local-test-only'], 'create-worker', 0)
    guard = c.out/'network_guard'
    write(guard/'sitecustomize.py', '''import sys, socket, ipaddress, json, os
def audit(event, args):
    if event != 'socket.connect': return
    sock, address = args
    if sock.family not in (socket.AF_INET, socket.AF_INET6): return
    host = address[0]
    try: allowed = ipaddress.ip_address(host).is_loopback
    except ValueError: allowed = host == 'localhost'
    with open(os.environ['CPG_NETWORK_AUDIT'], 'a') as f:
        f.write(json.dumps({'event': event, 'host': host, 'port': address[1], 'allowed': allowed})+'\\n')
    if not allowed: raise PermissionError('CPG acceptance permits loopback connections only')
sys.addaudithook(audit)
''')
    processes, streams = [], []
    try:
        for command, name in [([exe, 'start', '--nodaemon', master], 'master'),
                              ([workerexe, 'start', '--nodaemon', worker], 'worker')]:
            stream = (c.out / (name + '-service.log')).open('w')
            streams.append(stream)
            service_env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
                           'PYTHONPATH': str(guard), 'CPG_NETWORK_AUDIT': str(c.out/'network-audit.jsonl')}
            proc = subprocess.Popen(list(map(str, command)), cwd=c.out, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True,
                                    env=service_env)
            processes.append(proc)
        deadline = time.monotonic() + 70
        builds = []
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                raise AssertionError('Buildbot service exited; inspect master-service.log and worker-service.log')
            try:
                with sqlite3.connect(master / 'state.sqlite') as db:
                    db.row_factory = sqlite3.Row
                    builds = [dict(r) for r in db.execute('select * from builds where complete_at is not null')]
            except sqlite3.OperationalError:
                pass
            if builds:
                break
            time.sleep(0.25)
        write(c.out / 'completed-builds.json', json.dumps(builds, indent=2) + '\n')
        c.require(bool(builds), 'a real master-scheduled build completed on the separate worker')
        c.require(all(r['results'] == 0 for r in builds), 'completed Buildbot build has SUCCESS result=0')
        results = list(worker.rglob('result.json'))
        c.require(bool(results), 'worker-produced compiled program result.json exists')
        data = json.loads(results[0].read_text())
        c.require(data == {'compiled': True, 'actual': 42, 'expected': 42},
                  'worker compiled and executed a C program with verified output=42')
        events=[json.loads(line) for line in (c.out/'network-audit.jsonl').read_text().splitlines()]
        c.require(bool(events) and all(e['allowed'] for e in events),
                  'Python socket audit observes only allowed loopback connections')
        c.require('buildbotNetUsageData: sending' not in (master/'twistd.log').read_text(),
                  'telemetry disabled before service start; no telemetry sending event')
        return {'scope': 'fresh localhost master, separate worker process and directories; no upstream master or publishing',
                'build_results': builds, 'worker_result': data, 'pb_bind': f'127.0.0.1:{port}'}
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try: p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=5)
        for stream in streams:
            stream.close()


def cdash(c):
    cmake = c.prefix / 'tools/cmake/bin/cmake'
    ctest = c.prefix / 'tools/cmake/bin/ctest'
    source = c.out / 'project'; build = c.out / 'build'
    write(source / 'CMakeLists.txt', '''cmake_minimum_required(VERSION 3.20)
project(CPGCTestSubmission C)
include(CTest)
add_executable(answer answer.c)
add_test(NAME correct_answer COMMAND answer)
set_tests_properties(correct_answer PROPERTIES PASS_REGULAR_EXPRESSION "answer=42")
add_test(NAME expected_failure COMMAND ${CMAKE_COMMAND} -E false)
set_tests_properties(expected_failure PROPERTIES WILL_FAIL TRUE)
add_test(NAME deliberate_regression COMMAND ${CMAKE_COMMAND} -E false)
''')
    write(source / 'answer.c', '#include <stdio.h>\nint main(void){puts("answer=42");return 0;}\n')
    write(source / 'CTestConfig.cmake', '''set(CTEST_PROJECT_NAME "CPGCTestSubmission")
set(CTEST_NIGHTLY_START_TIME "00:00:00 UTC")
''')
    c.run([cmake, '-S', source, '-B', build], 'cmake-configure', 0)
    p = c.run([ctest, '-D', 'ExperimentalConfigure', '-D', 'ExperimentalBuild',
               '-D', 'ExperimentalTest', '--output-on-failure'], 'ctest-dashboard-local', cwd=build)
    c.require(p.returncode != 0, 'deliberate regression makes the CTest run nonzero')
    xmls = list((build / 'Testing').glob('*/Test.xml'))
    c.require(len(xmls) == 1, 'CTest generated exactly one submission Test.xml')
    root = ET.parse(xmls[0]).getroot()
    tests = {t.findtext('Name'): t for t in root.findall('./Testing/Test')}
    c.require(set(tests) == {'correct_answer', 'expected_failure', 'deliberate_regression'},
              'submission has all three expected test identities')
    expected = {'correct_answer': 'passed', 'expected_failure': 'passed', 'deliberate_regression': 'failed'}
    statuses = {k: v.attrib['Status'] for k,v in tests.items()}
    c.require(statuses == expected, 'submission statuses preserve positive, expected failure, and actual regression semantics')
    for filename in ['Configure.xml','Build.xml','Test.xml']:
        path=xmls[0].parent/filename
        c.require(path.is_file(), f'{filename} exists and parses')
        ET.parse(path);shutil.copy2(path,c.out/filename)
    write(c.out / 'parsed-submission.json', json.dumps({'site': root.attrib,'tests': statuses}, indent=2)+'\n')
    c.require((c.prefix/'share/cdash').is_dir(), 'frozen complete CDash source is locally available')
    return {'scope': 'offline generation/parsing of actual CTest CDash submission; no dashboard service or upload',
            'test_statuses': statuses, 'server_deployed': False, 'submitted': False}


def reframe(c):
    config = write(c.out / 'settings.py', '''import os
site_configuration = {
    'general': [{'topology_prefix': os.path.join(os.path.dirname(__file__), 'topology')}],
    'systems': [{'name': 'local', 'descr': 'local bounded CPG acceptance',
                 'hostnames': ['.*'], 'modules_system': 'nomod',
                 'partitions': [{'name': 'cpu', 'scheduler': 'local', 'launcher': 'local',
                                  'environs': ['builtin-gcc']}]}],
    'environments': [{'name': 'builtin-gcc', 'cc': 'gcc', 'cxx': 'g++', 'ftn': 'gfortran'}]
}
''')
    checks = write(c.out / 'checks.py', '''import reframe as rfm
import reframe.utility.sanity as sn
@rfm.simple_test
class CPGCompileRun(rfm.RegressionTest):
    size = parameter([1000, 10000])
    valid_systems = ['local:cpu']
    valid_prog_environs = ['builtin-gcc']
    build_system = 'SingleSource'
    sourcepath = 'kernel.c'
    sourcesdir = 'src'
    executable = './kernel'
    @run_before('compile')
    def configure(self):
        self.build_system.cflags = ['-O2', '-Wall', '-Werror']
        self.executable_opts = [str(self.size)]
    @sanity_function
    def validate(self):
        return sn.assert_eq(sn.extractsingle(r'sum=(\\d+)', self.stdout, 1, int), self.size*(self.size-1)//2)
    @performance_function('s')
    def elapsed(self):
        return sn.extractsingle(r'elapsed=([0-9.]+)', self.stdout, 1, float)
''')
    write(c.out/'src/kernel.c', '''#include <stdio.h>
#include <stdlib.h>
#include <time.h>
int main(int argc, char **argv) {
  if(argc!=2)return 2;
  long n=atol(argv[1]); volatile long sum=0;
  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  for(long i=0;i<n;i++)sum+=i;
  clock_gettime(CLOCK_MONOTONIC,&b);
  double t=(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)*1e-9;
  printf("sum=%ld elapsed=%.9f\\n",sum,t);return 0;
}
''')
    report = c.out/'report.json'
    p=c.run([c.prefix/'bin/reframe','-C',config,'-c',checks,'-r','--keep-stage-files',
             '--prefix',c.out/'run','--report-file',report], 'parameterized-run', 0,timeout=120)
    d=json.loads(report.read_text())
    cases=d['runs'][0]['testcases']
    c.require(len(cases)==2, 'both parameterized compile/run cases appear in the report')
    c.require(all(x['result']=='pass' for x in cases), 'both cases pass real compilation, execution, and sanity checks')
    c.require(all(x.get('perfvalues') for x in cases), 'both cases export measured performance variables')
    return {'scope':'local scheduler and launcher only; no MPI/GPU/cluster claims',
            'cases':[{'name':x['name'],'result':x['result'],'perfvalues':x['perfvalues']} for x in cases]}


def jtreg(c):
    suite=c.out/'tests'
    write(suite/'TEST.ROOT', 'keys=acceptance\n')
    write(suite/'Positive.java', '''/* @test
 * @summary Positive compiler/runtime fixture
 * @run main Positive
 */
public class Positive { public static void main(String[] args) {
  if (6*7 != 42) throw new AssertionError();
  System.out.println("CPG_JTREG_POSITIVE_42");
}}
''')
    write(suite/'ExpectedFailure.java', '''/* @test
 * @summary Expected failure must be recognized as PASS
 * @run main/fail ExpectedFailure
 */
public class ExpectedFailure { public static void main(String[] args) {
  throw new AssertionError("CPG_EXPECTED_FAILURE");
}}
''')
    write(suite/'UnexpectedFailure.java', '''/* @test
 * @summary Deliberate negative control must be reported FAILED
 * @run main UnexpectedFailure
 */
public class UnexpectedFailure { public static void main(String[] args) {
  throw new AssertionError("CPG_UNEXPECTED_FAILURE");
}}
''')
    env=dict(os.environ, JAVA_HOME=str(c.prefix/'jdk'), JTREG_HOME=str(c.prefix/'jtreg'),
             JTREG_JAVA=str(c.prefix/'jdk/bin/java'))
    exe=c.prefix/'jtreg/bin/jtreg'
    base=['bash',exe,'-jdk:'+str(c.prefix/'jdk'),'-othervm','-verbose:summary','-concurrency:2',
          '-J-Xmx256m','-J-XX:ActiveProcessorCount=2',
          '-vmoption:-Xmx128m','-vmoption:-XX:ActiveProcessorCount=2']
    c.run(base+['-w:'+str(c.out/'positive-work'),'-r:'+str(c.out/'positive-report'),
                suite/'Positive.java',suite/'ExpectedFailure.java'],'expected-results',0,env=env,timeout=180)
    p=c.run(base+['-w:'+str(c.out/'negative-work'),'-r:'+str(c.out/'negative-report'),
                  suite/'UnexpectedFailure.java'],'negative-control',env=env,timeout=120)
    c.require(p.returncode!=0,'unexpected failure returns nonzero')
    results={}
    for name,folder in [('Positive','positive-work'),('ExpectedFailure','positive-work'),('UnexpectedFailure','negative-work')]:
        path=c.out/folder/(name+'.jtr');text=path.read_text()
        m=re.search(r'^execStatus=(.+)$',text,re.M)
        c.require(m is not None,f'{name}: jtr includes machine-readable execStatus')
        results[name]=m.group(1)
    c.require(results['Positive'].startswith('Passed.'),'positive case is Passed')
    c.require(results['ExpectedFailure'].startswith('Passed.'),'@run main/fail case is Passed')
    c.require(results['UnexpectedFailure'].startswith('Failed.'),'unexpected-failure negative control is Failed')
    c.run([c.prefix/'jdk/bin/java','-version'],'jdk-version',0)
    c.run(['bash',exe,'-version'],'jtreg-version',0,env=env)
    write(c.out/'parsed-jtr.json',json.dumps(results,indent=2)+'\n')
    return {'scope':'JDK17 plus pinned jtreg, local Java fixtures only; not full OpenJDK tier suite','results':results}


def benchexec(c):
    probes={}
    for path in ['/proc/self/cgroup','/sys/fs/cgroup/cgroup.controllers','/sys/fs/cgroup/cgroup.subtree_control']:
        try:probes[path]=Path(path).read_text()
        except OSError as e:probes[path]=str(e)
    probes['cgroup_writable']=os.access('/sys/fs/cgroup',os.W_OK)
    u=c.run(['unshare','-Urn','true'],'namespace-probe')
    probes['namespace_exit']=u.returncode
    write(c.out/'host-prerequisites.json',json.dumps(probes,indent=2)+'\n')
    cpu=write(c.out/'cpu.c','int main(void){volatile unsigned long x=0;for(;;)x++;}\n')
    mem=write(c.out/'memory.c', '''#include <stdlib.h>
#include <string.h>
int main(void){for(;;){void *p=malloc(1024*1024);if(!p)return 3;memset(p,1,1024*1024);}}
''')
    c.run(['gcc','-O0',cpu,'-o',c.out/'cpu'],'compile-cpu-fixture',0)
    c.run(['gcc','-O0',mem,'-o',c.out/'memory'],'compile-memory-fixture',0)
    exe=c.prefix/'bin/runexec'
    results={}
    for name,opts in [('cpu',['--timelimit','1','--walltimelimit','6']),
                      ('memory',['--memlimit','33554432','--walltimelimit','6'])]:
        p=c.run([exe,'--container','--read-only-dir','/','--full-access-dir',c.out,
                 '--output',c.out/(name+'-program.log')]+opts+['--',c.out/name],name+'-limited-run',timeout=30)
        results[name]={'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    failed_setup=any('terminationreason=' not in r['stdout'] for r in results.values())
    if failed_setup:
        diagnostics='\n'.join(r['stderr'] for r in results.values())
        known=bool(re.search(r'cgroup|namespace|permission|not permitted|read.only|clone|mount',diagnostics,re.I))
        c.require(known,'missing isolation result has explicit cgroup/namespace/permission setup diagnostic')
        return {'status':'blocked','scope':'cgroup and namespace based resource isolation',
                'reason':'host does not provide usable delegated cgroups and/or namespaces; no ulimit fallback',
                'host':probes,'limit_results':results,'after_functional':False}
    c.require(re.search(r'terminationreason=(cputime|cputime-soft)',results['cpu']['stdout']) is not None,
              'CPU limit is reported as cputime by BenchExec')
    c.require('terminationreason=memory' in results['memory']['stdout'],
              'memory limit is reported as memory by BenchExec')
    return {'scope':'real cgroup and namespace CPU/memory enforcement','limit_results':results}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--resource',required=True)
    ap.add_argument('--prefix',required=True);ap.add_argument('--output',required=True)
    a=ap.parse_args();c=Check(a.prefix,a.output)
    result={'resource':a.resource,'status':'failed','offline':a.resource!='buildbot',
            'network_mode':'loopback-only with Python socket audit' if a.resource=='buildbot' else 'offline'}
    code=1
    try:
        extra=globals()[a.resource](c);result['status']='passed';result.update(extra)
        code=77 if result['status']=='blocked' else 0
    except Exception as e:
        result['error']=repr(e)
    result.update(commands=c.commands,assertions=c.assertions,evidence_directory=str(c.out))
    write(c.out/'summary.json',json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return code


if __name__=='__main__':
    sys.exit(main())
