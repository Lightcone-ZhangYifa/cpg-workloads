#!/usr/bin/env python3
"""Bounded, deterministic semantic checks for worker 074 resources.

Only generated test programs are instrumented. No process enumeration or
external network access is used. Every subprocess exit status is checked.
"""
from __future__ import annotations
import argparse, json, os, pathlib, subprocess, sys, time, threading, re

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('kind');ap.add_argument('prefix');ap.add_argument('work');args=ap.parse_args()
    p=pathlib.Path(args.prefix).resolve();w=pathlib.Path(args.work).resolve();w.mkdir(parents=True,exist_ok=True)
    result=w/'result.json';result.unlink(missing_ok=True)
    env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONNOUSERSITE']='1';env['PYTHONPATH']=str(p/'python')
    sys.path.insert(0,str(p/'python'));sys.dont_write_bytecode=True
    records=[]
    def run(argv,*,timeout=90,check=True,extra_env=None):
        e=env.copy();e.update(extra_env or {})
        r=subprocess.run([str(x) for x in argv],cwd=w,env=e,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        n=len(records)+1;(w/f'{n:02d}.stdout.txt').write_text(r.stdout);(w/f'{n:02d}.stderr.txt').write_text(r.stderr)
        records.append({'argv':[str(x) for x in argv],'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
        if check:require(r.returncode==0,'command failed: '+repr(argv)+'\n'+r.stderr[-3000:])
        return r
    report={'kind':args.kind,'scope':'Generated local x86_64 test programs only; no performance qualification.'}
    if args.kind=='gtirb':
        import gtirb
        ir=gtirb.IR();m=gtirb.Module(name='cpg-symbol-cfg',isa=gtirb.Module.ISA.X64,file_format=gtirb.Module.FileFormat.ELF,ir=ir)
        sec=gtirb.Section(name='.text',flags={gtirb.Section.Flag.Readable,gtirb.Section.Flag.Executable},module=m)
        bi=gtirb.ByteInterval(address=0x400000,size=8,contents=b'\x83\xff\x00\x74\x01\xc3\x90\xc3',section=sec)
        a=gtirb.CodeBlock(offset=0,size=5,byte_interval=bi);b=gtirb.CodeBlock(offset=5,size=1,byte_interval=bi);c=gtirb.CodeBlock(offset=6,size=2,byte_interval=bi)
        entry=gtirb.Symbol('entry',payload=a,module=m);target=gtirb.Symbol('target',payload=c,module=m)
        ir.cfg.add(gtirb.Edge(a,c,gtirb.Edge.Label(type=gtirb.Edge.Type.Branch,conditional=True,direct=True)))
        ir.cfg.add(gtirb.Edge(a,b,gtirb.Edge.Label(type=gtirb.Edge.Type.Fallthrough)))
        bi.symbolic_expressions[4]=gtirb.SymAddrConst(0,target)
        m.entry_point=a;m.aux_data['cpgSymbols']=gtirb.AuxData([entry,target],'sequence<UUID>')
        ir.save_protobuf(str(w/'fixture.gtirb'));other=gtirb.IR.load_protobuf(str(w/'fixture.gtirb'))
        require(ir.deep_eq(other),'GTIRB protobuf round trip differs')
        om=other.modules[0];symbols={x.name:x for x in om.symbols};nodes={x.uuid:x for x in om.code_blocks}
        require(len(nodes)==3 and len(other.cfg)==2 and set(symbols)=={'entry','target'},'IR structure differs')
        require(symbols['entry'].referent.uuid==a.uuid and symbols['target'].referent.uuid==c.uuid,'symbol reference mismatch')
        require(all(edge.source.uuid in nodes and edge.target.uuid in nodes for edge in other.cfg),'CFG dangling node')
        require(next(iter(om.byte_intervals)).symbolic_expressions[4].symbol.uuid==target.uuid,'symbolic expression lost')
        require({x.uuid for x in om.aux_data['cpgSymbols'].data}=={entry.uuid,target.uuid},'auxdata references lost')
        # A mutated graph must be distinguishable from the accepted graph.
        other.cfg.clear();require(not ir.deep_eq(other),'graph mutation was not detected')
        report.update(blocks=3,cfg_edges=2,symbols=2,symbolic_reference=True,auxdata_reference=True,negative_graph_mutation=True)
    elif args.kind=='ddisasm':
        import gtirb
        src=w/'fixture.c';src.write_text('#include <stdio.h>\n#include <stdlib.h>\n__attribute__((noinline,visibility("default"))) int compute(int x){int s=0; for(int i=0;i<5;i++) s += (x+i<0)?-(x+i):(x+i)*3; return s;}\nint main(int c,char **v){int x=c>1?atoi(v[1]):0; printf("%d\\n",compute(x)); return 0;}\n')
        run(['gcc','-O1','-g','-fno-inline','-fPIE','-pie','-Wl,--export-dynamic',src,'-o',w/'original'])
        run([sys.executable,'-m','ddisasm',w/'original','--ir',w/'fixture.gtirb','-j','1'],timeout=180)
        ir=gtirb.IR.load_protobuf(str(w/'fixture.gtirb'));require(len(ir.modules)==1,'unexpected module count');m=ir.modules[0]
        syms={s.name:s for s in m.symbols};require('compute' in syms and isinstance(syms['compute'].referent,gtirb.CodeBlock),'compute symbol not attached to code')
        blocks=list(m.code_blocks);require(len(blocks)>5,'insufficient CFG recovery')
        for block in blocks:require(block.byte_interval is not None and block.offset+block.size<=block.byte_interval.size,'block outside byte interval')
        require(any(e.label and e.label.conditional and e.label.type==gtirb.Edge.Type.Branch for e in ir.cfg),'no conditional branch recovered')
        ids={n.uuid for n in m.cfg_nodes};require(all(e.source.uuid in ids and e.target.uuid in ids for e in ir.cfg),'dangling CFG endpoint')
        require(any(syms['compute'].referent in entries for entries in m.aux_data['functionEntries'].data.values()),'compute missing from functionEntries')
        run([sys.executable,'-m','gtirb_pprinter',w/'fixture.gtirb','--asm',w/'rewritten.s','--binary',w/'rewritten'],timeout=120)
        outputs=[]
        for x in (-9,-1,0,1,7,20):
            expected=sum(-(x+i) if x+i<0 else (x+i)*3 for i in range(5))
            aout=run([w/'original',x]).stdout;bout=run([w/'rewritten',x]).stdout
            require(aout==bout==f'{expected}\n','ELF semantic mismatch');outputs.append({'input':x,'output':expected})
        report.update(code_blocks=len(blocks),cfg_edges=len(ir.cfg),function_symbol='compute',control_flow_boundaries=True,outputs=outputs)
    elif args.kind=='frida':
        import frida
        src=w/'fixture.c';src.write_text('#include <stdio.h>\n#include <unistd.h>\n__attribute__((noinline,visibility("default"))) int calculate(int x){return 3*x+1;}\nint main(int argc,char **argv){if(argc>1){char ch;if(read(0,&ch,1)!=1)return 3;}int a[]={0,1,-4,7};for(int i=0;i<4;i++)printf("%d:%d\\n",a[i],calculate(a[i]));return 0;}\n')
        run(['gcc','-O0','-g','-fno-inline','-fPIE','-pie','-Wl,--export-dynamic',src,'-o',w/'original'])
        expected='0:1\n1:4\n-4:-11\n7:22\n';require(run([w/'original']).stdout==expected,'native reference differs')
        device=frida.get_local_device();messages=[];session=None;child=None
        try:
            child=subprocess.Popen([str(w/'original'),'wait'],cwd=w,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            # The PID comes only from this child's creation; wait until libc has
            # entered read(0), then attach to the initialized, owned process.
            time.sleep(0.2);require(child.poll() is None,'fixture exited before hook')
            session=device.attach(child.pid)
            symbols=run(['nm','-n',w/'original']).stdout.splitlines()
            addresses=[int(line.split()[0],16) for line in symbols if line.split()[-1:] == ['calculate']]
            require(len(addresses)==1,'owned fixture calculate symbol is ambiguous')
            address=addresses[0]
            script=session.create_script('const target=Process.mainModule.base.add('+str(address)+'); Interceptor.attach(target, {onEnter(args){this.x=args[0].toInt32();},onLeave(retval){send({input:this.x, output:retval.toInt32()});}});')
            script.on('message',lambda msg,data:messages.append(msg));script.load()
            out,err=child.communicate(b'X',timeout=15);require(child.returncode==0,'instrumented process failed')
            time.sleep(0.2)
            (w/'frida-messages.json').write_text(json.dumps(messages,indent=2))
            require(not [m for m in messages if m.get('type')=='error'],'Frida script error '+repr(messages))
            observations=[m['payload'] for m in messages if m.get('type')=='send']
            require(observations==[{'input':x,'output':3*x+1} for x in (0,1,-4,7)],'hook argument/return mismatch')
            require(out.decode()==expected,'instrumented stdout changed')
            report.update(hook_observations=observations,stdout=expected,spawned_own_process_only=True,elf_symbol_offset=address,address_resolution='owned PIE ELF symbol plus module load base')
        finally:
            if session is not None:
                try:session.detach()
                except frida.InvalidOperationError:pass
            if child is not None and child.poll() is None:child.kill();child.wait()
    elif args.kind=='dynamorio':
        src=w/'fixture.c';src.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(int c,char **v){int n=c>1?atoi(v[1]):0; unsigned long long sum=0;for(int i=0;i<n;i++)sum+=(unsigned)(i^(3*i));printf("%llu\\n",sum);return 0;}\n')
        run(['gcc','-O0','-g',src,'-o',w/'original'])
        sdk=p/'sdk';client_source=p/'examples/dr_client.c';client=w/'client.so'
        run(['gcc','-DLINUX','-DX86_64','-shared','-fPIC','-fno-stack-protector','-Wl,--hash-style=both','-Wl,-z,now','-I'+str(sdk/'include'),client_source,'-L'+str(sdk/'lib64/release'),'-ldynamorio','-o',client])
        cases=[]
        for n in (10,1000,10000):
            expected=str(sum(i^(3*i) for i in range(n)))+'\n';plain=run([w/'original',n]);observed=run([sdk/'bin64/drrun','-quiet','-c',client,'--',w/'original',n])
            require(plain.stdout==observed.stdout==expected,'DynamoRIO changed stdout or arithmetic oracle failed')
            counts=re.findall(r'CPG_BB_COUNT=(\d+)',observed.stderr);require(len(counts)==1 and int(counts[0])>0,'missing bb callback events')
            cases.append({'iterations':n,'expected_stdout':expected,'basic_block_events':int(counts[0])})
        require(cases[0]['basic_block_events']<cases[1]['basic_block_events']<cases[2]['basic_block_events'],'bb events do not increase for generated loop')
        report.update(cases=cases,client_built_from_source=True)
    else:
        raise RuntimeError('unknown check kind '+args.kind)
    report.update(status='passed',commands=records)
    result.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
