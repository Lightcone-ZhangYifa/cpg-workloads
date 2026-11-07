#!/usr/bin/env python3
"""Offline gem5 RISC-V SE acceptance. All guest/runtime writes stay in output."""
import argparse,configparser,gzip,hashlib,json,os,re,resource,shutil,subprocess,tempfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    p=a.prefix.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);w=Path(tempfile.mkdtemp(prefix='run-',dir=out));checks=[];commands=[]
    def need(v,n):
        if not v:raise RuntimeError(n)
        checks.append({'name':n,'status':'passed'})
    env={k:v for k,v in os.environ.items() if not k.startswith('LD_') and not k.startswith('PYTHON')}
    env.update(LD_LIBRARY_PATH=str(p/'lib'),PYTHONHOME=str(p/'python'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',LC_ALL='C',OMP_NUM_THREADS='1')
    binary=p/'bin/gem5-mesi';identity=json.loads((p/'runtime-identity.json').read_text())
    cfg=w/'se-riscv.py';shutil.copy2(p/'fixtures/se-riscv.py',cfg)
    lock=json.loads((p/'fixtures/workload-lock.json').read_text());guest=w/lock['file'];data=gzip.decompress((p/'fixtures/hello-riscv64.gz').read_bytes());need(len(data)==lock['bytes'] and hashlib.sha256(data).hexdigest()==lock['sha256'],'exact locked RV64 guest bytes');need(data[:6]==b'\x7fELF\x02\x01' and int.from_bytes(data[18:20],'little')==243,'workload is ELF64 little-endian RISC-V');guest.write_bytes(data);guest.chmod(0o755)
    def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    def run(name,args,positive=True,timeout=120):
        d=w/name;d.mkdir();cmd=[str(binary),*map(str,args)]
        z=subprocess.run(cmd,cwd=d,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout,preexec_fn=no_core)
        (d/'console.log').write_text(z.stdout);commands.append({'name':name,'argv':cmd,'returncode':z.returncode})
        if (z.returncode==0)!=positive:raise RuntimeError(name+' unexpected process exit\n'+z.stdout[-6000:])
        need(True,name+' expected process exit');return d,z.stdout
    need(hashlib.file_digest(binary.open('rb'),'sha256').hexdigest()==identity['binary_sha256'],'exact official-derived native simulator SHA256')
    d=w/'positive';d.mkdir();m5out=d/'m5out';exitfile=d/'exit.json'
    cmd=[str(binary),'-q','--listener-mode=off','--outdir='+str(m5out),str(cfg),'--workload',str(guest),'--exit-json',str(exitfile)]
    z=subprocess.run(cmd,cwd=d,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=600,preexec_fn=no_core)
    (d/'console.log').write_text(z.stdout);commands.append({'name':'positive-SE','argv':cmd,'returncode':z.returncode})
    need(z.returncode==0,'positive syscall-emulation process exit 0; '+z.stdout[-800:] if z.returncode else 'positive syscall-emulation process exit 0')
    need('Hello world!' in z.stdout,'guest stdout contains upstream hello result');need(exitfile.is_file(),'simulator wrote structured exit evidence')
    exitdata=json.loads(exitfile.read_text());need(exitdata['code']==0 and exitdata['cause']=='exiting with last active thread context','normal guest completion cause/code');need(0<exitdata['simTicks']<exitdata['tick_budget'],'completed within fixed simulated tick budget')
    for fn in ['config.ini','config.json','stats.txt']:need((m5out/fn).is_file(),'saved '+fn)
    conf=configparser.ConfigParser(interpolation=None);conf.read(m5out/'config.ini')
    need(conf['system']['mem_mode']=='atomic','atomic memory mode in emitted config');need(conf['system.cpu']['type']=='BaseAtomicSimpleCPU' and exitdata['cpu_python_class']=='RiscvAtomicSimpleCPU','explicit RISC-V atomic CPU Python class and C++ type');need(conf['root']['full_system']=='false','syscall-emulation mode in emitted config');need(conf['system.clk_domain']['clock']=='1000','1 GHz clock at 1 ps global tick')
    isas=[conf[s].get('type','') for s in conf.sections() if s.startswith('system.cpu.isa')];need(any('RiscvISA'==v for v in isas),'RISC-V ISA object in config')
    need(conf['system.mem_ctrl.dram']['type']=='DRAMInterface' and exitdata['dram_python_class']=='DDR3_1600_8x8' and conf['system.mem_ctrl.dram']['tck']=='1250' and conf['system.mem_ctrl.dram']['device_bus_width']=='8','fixed DDR3 class and emitted bus/clock parameters')
    need(conf['system.cpu.isa']['riscv_type']=='RV64','RV64 ISA width in config')
    need(conf['system']['mem_ranges']=='0:134217728','fixed 128 MiB memory range in config')
    need(exitdata['observed_version_fields']['_m5.core.gem5Version']==identity['display_version'],'actual embedded gem5 version 24.0.0.0')
    need('Sockets disabled, not accepting gdb connections' in z.stdout,'remote GDB listener explicitly disabled')
    stats={}
    for line in (m5out/'stats.txt').read_text().splitlines():
        m=re.match(r'^(simTicks|simInsts|simOps|simSeconds)\s+([0-9.eE+-]+)',line)
        if m:stats[m.group(1)]=float(m.group(2))
    need(stats.get('simTicks',0)>0 and stats.get('simInsts',0)>0,'positive simulated ticks and instructions');need(int(stats['simTicks'])==exitdata['simTicks'],'stats ticks agree with structured simulator exit')
    invalid=w/'invalid-workload.bin';invalid.write_bytes(b'CPG deliberately invalid ELF fixture\n')
    nd=w/'negative';nd.mkdir();nout=nd/'m5out'
    cmd=[str(binary),'-q','--listener-mode=off','--outdir='+str(nout),str(cfg),'--workload',str(invalid),'--exit-json',str(nd/'exit.json')]
    z=subprocess.run(cmd,cwd=nd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=300,preexec_fn=no_core)
    (nd/'console.log').write_text(z.stdout);commands.append({'name':'negative-invalid-workload','argv':cmd,'returncode':z.returncode})
    need(z.returncode!=0,'invalid guest rejected with nonzero exit');need('CPG_GEM5_EXIT' not in z.stdout and not (nd/'exit.json').exists(),'invalid guest never reaches simulated normal completion');need('ValueError: '+str(invalid)+': the file is not an object file compatible with gem5.' in z.stdout and 'find_compatible' in z.stdout and 'init_compatible' in z.stdout,'negative rejected specifically by gem5 incompatible-object workload loader')
    (w/'commands.json').write_text(json.dumps(commands,indent=2));(w/'environment.json').write_text(json.dumps({'LD_LIBRARY_PATH':env['LD_LIBRARY_PATH'],'PYTHONHOME':env['PYTHONHOME'],'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','listener_mode':'off','network_resource_resolution':False},indent=2))
    summary={'actual_binary_version':identity['display_version'],'runtime_identity':identity,'guest':lock,'configuration':exitdata,'simulator_statistics':stats,'host_wall_clock_used_for_comparison':False,'hardware_measurement':False}
    (w/'simulation-summary.json').write_text(json.dumps(summary,indent=2))
    files=[str(f.relative_to(out)) for f in sorted(w.rglob('*')) if f.is_file() and f!=guest]
    result={'status':'passed','resource':'research.gem5','checks':checks,'metrics':summary,'evidence_files':files,'limitations':['The fixed RV64 hello SE program and RiscvAtomicSimpleCPU model are qualified; no other CPU/ISA/full-system profile is claimed.','Ticks and instruction counts describe this simulation, not target hardware or host performance.','The native simulator is an official digest-locked OCI prebuilt; no local simulator source build is claimed.','Runtime uses bundled CPython/selected private libraries plus declared Linux x86_64 host libraries validated by the original CPG ELF checker.']}
    (out/'result.json').write_text(json.dumps(result,indent=2));print('CPG_CHECK_PASS research.gem5')
if __name__=='__main__':main()
