#!/usr/bin/env python3
"""Bounded offline resource checks. No collector, GPU query, PMU or network client is called."""
from pathlib import Path
import argparse,csv,gzip,hashlib,io,json,os,re,shutil,subprocess,sys,tempfile,xml.etree.ElementTree as ET
sys.dont_write_bytecode=True

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--build',required=True);a=ap.parse_args()
 p=Path(a.prefix).resolve();b=Path(a.build).resolve();b.mkdir(parents=True,exist_ok=True)
 if b==p or p in b.parents:raise ValueError('check build directory must be outside the immutable prefix')
 out=Path(tempfile.mkdtemp(prefix='worker076-check-',dir=b))
 policy=json.loads((p/'CPG-POLICY.json').read_text());eid=policy['package_id'];runs=[];checks=[]
 def expect(ok,label,**kw):
  checks.append({'name':label,'passed':bool(ok),**kw})
  if not ok:raise AssertionError(label+' '+repr(kw))
 def run(name,argv,stdin=None,expected=0,env=None):
  q=subprocess.run([str(x) for x in argv],input=stdin,text=True,capture_output=True,cwd=out,env=env,timeout=120)
  (out/(name+'.stdout')).write_text(q.stdout);(out/(name+'.stderr')).write_text(q.stderr)
  row={'case':name,'argv':[str(x) for x in argv],'returncode':q.returncode,'stdout_sha256':hashlib.sha256(q.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(q.stderr.encode()).hexdigest()};runs.append(row)
  expect(q.returncode==expected,name+' exit',observed=q.returncode,expected=expected,stderr=q.stderr[-400:]);return q
 def verify_material():
  m=json.loads((p/'material-manifest.json').read_text());found=[]
  for row in m['files']:
   q=p/row['path'];expect(q.is_file() and not q.is_symlink(),'material regular '+row['path'])
   expect(q.stat().st_size==row['bytes'] and sha(q)==row['sha256'],'material hash '+row['path'])
   found.append(row['path'])
  expect(len(found)==len(set(found)),'unique material paths')
  expect(policy['capture_enabled'] is False and policy['device_control_enabled'] is False,'policy prohibits capture and controls')
  return len(found)
 try:
  files=verify_material()
  if eid=='flamegraph.offline-w076':
   ex=json.loads((p/'fixtures/expectations.json').read_text());perl=shutil.which('perl');expect(bool(perl),'perl prerequisite')
   data=gzip.decompress((p/ex['upstream_saved_trace']).read_bytes()).decode()
   records=re.findall(r'^\S.*?\s+\d+(?:/\d+)?\s+\[\d+\]\s+\d+\.\d+:\s+cycles:\s*$',data,re.M)
   expect(len(records)==ex['upstream_header_count'],'independent saved perf header count',count=len(records))
   folded=run('saved-perf-collapse',[perl,p/'upstream/stackcollapse-perf.pl'],data).stdout
   weights=[int(x.rsplit(' ',1)[1]) for x in folded.splitlines() if x]
   expect(sum(weights)==len(records),'saved perf total folded weight',sum=sum(weights))
   svg=run('saved-perf-svg',[perl,p/'upstream/flamegraph.pl','--hash','--countname','samples'],folded).stdout
   root=ET.fromstring(svg);titles=[x.text or '' for x in root.iter() if x.tag.rsplit('}',1)[-1]=='title']
   expect(any(x==f'all ({len(records):,} samples, 100%)' or re.fullmatch(r'all \('+f'{len(records):,}'+r' samples, 100(?:\.0+)?%\)',x) for x in titles),'saved SVG root sample count')
   collapsed=run('controlled-weight-collapse',[perl,p/'upstream/stackcollapse-perf.pl','--event-filter','cycles'],(p/'fixtures/weighted-perf-script.txt').read_text()).stdout
   actual={x.rsplit(' ',1)[0]:int(x.rsplit(' ',1)[1]) for x in collapsed.splitlines() if x}
   expect(actual==ex['controlled_folded'],'period-weight exact folded paths',actual=actual)
   small=run('controlled-svg',[perl,p/'upstream/flamegraph.pl','--hash','--countname','period-units'],collapsed).stdout
   sr=ET.fromstring(small);st=[x.text or '' for x in sr.iter() if x.tag.rsplit('}',1)[-1]=='title']
   expect(any('all (15 period-units, 100' in x for x in st),'controlled SVG period count')
   bad=run('reject-invalid-folded',[perl,p/'upstream/flamegraph.pl'],'not a folded record\n',expected=2)
   expect('ERROR' in bad.stderr or 'No stack counts' in bad.stderr,'invalid folded diagnostic')
  elif eid=='perfetto-analysis':
   exe=p/'bin/trace_processor_shell';trace=p/'fixtures/compile-trace.json';ex=json.loads((p/'fixtures/expectations.json').read_text())
   def sql(name,text):
    q=run(name,[exe,'query','--quiet','--no-agent','--format','csv',trace,text]);return list(csv.reader(io.StringIO(q.stdout)))
   rows=sql('phase-summary',(p/'fixtures/phase-summary.sql').read_text())
   parsed=[[x[0],int(x[1]),int(x[2])] for x in rows[1:]]
   expect(parsed==ex['slices'],'actual Perfetto slice aggregates',actual=parsed)
   rows=sql('thread-summary',(p/'fixtures/thread-summary.sql').read_text())
   expect([[int(y) for y in x] for x in rows[1:]]==[[10,11,5,8000000],[10,12,1,4000000],[20,21,1,500000]],'thread/process joins and timestamp units',actual=rows)
   rows=sql('counter-summary',(p/'fixtures/counter-summary.sql').read_text());expect([int(float(x[1])) for x in rows[1:]]==ex['counter_values'],'counter value import',actual=rows)
   rows=sql('arg-query',"SELECT EXTRACT_ARG(arg_set_id, 'args.phase') AS phase FROM slice WHERE name='parse' AND dur=2000000;")
   expect(rows[1:]==[['front-end']],'trace argument identity',actual=rows)
   rows=sql('deterministic-repeat',(p/'fixtures/phase-summary.sql').read_text());expect([[x[0],int(x[1]),int(x[2])] for x in rows[1:]]==ex['slices'],'repeat import has identical aggregates')
   q=subprocess.run([str(exe),'query','--quiet','--no-agent','--format','csv',str(trace),'SELECT definitely_missing FROM no_such_table;'],capture_output=True,text=True,cwd=out,timeout=30)
   (out/'bad-sql.stderr').write_text(q.stderr);(out/'bad-sql.stdout').write_text(q.stdout)
   runs.append({'case':'bad-sql','argv':q.args,'returncode':q.returncode,'stdout_sha256':hashlib.sha256(q.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(q.stderr.encode()).hexdigest(),'negative_case':True})
   expect(q.returncode!=0,'invalid SQL rejected',returncode=q.returncode)
   bad=out/'invalid.trace';bad.write_bytes(b'not a recognized trace\x00\xff')
   q=subprocess.run([str(exe),'query','--quiet','--no-agent','--format','csv',str(bad),'SELECT count(*) FROM slice;'],capture_output=True,text=True,cwd=out,timeout=30)
   (out/'bad-trace.stderr').write_text(q.stderr);(out/'bad-trace.stdout').write_text(q.stdout)
   runs.append({'case':'bad-trace','argv':q.args,'returncode':q.returncode,'stdout_sha256':hashlib.sha256(q.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(q.stderr.encode()).hexdigest(),'negative_case':True})
   expect(q.returncode!=0,'invalid trace rejected',returncode=q.returncode)
   expect((p/'ui/index.html').is_file() and bool(list((p/'ui').glob('*/trace_processor.wasm'))),'official offline UI and wasm present, execution not claimed')
  elif eid=='speedscope':
   node=shutil.which('node');expect(bool(node),'node prerequisite')
   q=run('actual-importer-cli',[node,p/'import-profile.cjs',p/'fixtures/compiler.speedscope.json']);result=json.loads(q.stdout)
   expect(result['status']=='passed' and len(result['profiles'])==2,'actual upstream importer returned two profiles')
   ex=json.loads((p/'fixtures/expectations.json').read_text())
   for i,k in enumerate(['sampled','evented']):
    z=result['profiles'][i];v=ex[k];expect(z['totalWeight']==v['total'] and z['nonIdleWeight']==v['non_idle'],k+' total/idle weights',actual=z)
    frames={f['name']:[f['totalWeight'],f['selfWeight']] for f in z['frames']}
    expect(frames==v['frames'],k+' per-frame weights and recursion handling',actual=frames)
   run('upstream-and-guard-negative-oracles',[node,p/'test-importer.cjs',p/'import-profile.cjs',p/'fixtures/compiler.speedscope.json'])
   expect((p/'upstream-npm/dist/release/index.html').is_file(),'official offline UI present; browser execution separate')
  elif eid=='nvtx':
   expectations=json.loads((p/'examples/expectations.json').read_text());clean={k:v for k,v in os.environ.items() if not k.startswith('NVTX_')};clean['LC_ALL']='C'
   for language,compiler,filename,std in [('C','cc','workload.c','c11'),('C++','c++','workload.cpp','c++11')]:
    cc=shutil.which(compiler);expect(bool(cc),compiler+' prerequisite')
    for mode,flags in [('plain',[]),('disabled',['-DCPG_ANNOTATE','-DNVTX_DISABLE']),('default-no-tool',['-DCPG_ANNOTATE'])]:
     binary=out/(language.replace('+','p')+'-'+mode)
     argv=[cc,'-std='+std,'-O2','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror','-I',p/'include',*flags,p/'examples'/filename,'-o',binary]
     if mode=='default-no-tool':argv+=['-ldl']
     run(language+'-compile-'+mode,argv,env=clean)
     for n in expectations['input_n']:
      x=run(language+'-'+mode+'-'+str(n),[binary,str(n)],env=clean)
      oracle=sum(i*i+7*i for i in range(n));expect(x.stdout==f'n={n} value={oracle}\n',language+' '+mode+' mathematical oracle '+str(n))
     if mode=='disabled' and shutil.which('nm'):
      nm=run(language+'-disabled-symbols',['nm','-u',binary]).stdout
      expect('nvtx' not in nm.lower() and 'dlopen' not in nm,'disabled binary has no NVTX/dlopen unresolved symbols')
  else:
   idx=json.loads((p/'reference-index.json').read_text());paths=idx['selected_reading_paths'];expect(bool(paths),'non-empty selected documentation/API inputs')
   for x in paths:expect((p/'reference'/x).is_file(),'indexed reference '+x)
   if eid=='amd-smi-materials':
    text=(p/'reference/include/amd_smi/amdsmi.h').read_text();api=json.loads((p/'identity-api.json').read_text())
    for name in api['identity_getters']:expect(name in text,'pinned AMD identity API '+name)
    expect(api['driver_observed'] is None and api['device_query_executed'] is False,'no invented AMD driver/device qualification')
   if eid=='nanobench-materials':
    expect('performance counters' in (p/'reference/README.md').read_text().lower(),'nanoBench counter role documented')
   if eid=='hpctoolkit-materials':
    expect((p/'reference/doc/FORMATS.md').is_file(),'HPCToolkit native input/database format reference')
   if eid=='nvml-reference':
    expect(idx['native_driver_payload_present'] is False and not (p/'reference/pkg/nvml/nvml.h').exists(),'NVML has no duplicated native driver/header payload')
    text=(p/'reference/pkg/nvml/device.go').read_text()+(p/'reference/pkg/nvml/system.go').read_text()
    for name in ['DeviceGetName','DeviceGetUUID','DeviceGetPciInfo','SystemGetDriverVersion','SystemGetNVMLVersion']:expect(name in text,'official NVML interface '+name)
  report={'status':'passed','package_id':eid,'scope':policy['qualification_scope'],'check_kind':policy['check_kind'],'material_files_verified':files,'assertions':len(checks),'subprocess_count':len(runs),'negative_subprocess_count':sum(bool(x.get('negative_case')) for x in runs),'checks':checks,'runs':runs,'output_dir':str(out),'collector_execution':False,'device_control':False,'hardware_measurement':False}
  (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['status','package_id','scope','check_kind','material_files_verified','assertions','subprocess_count','negative_subprocess_count','output_dir']},ensure_ascii=False))
 except Exception as exc:
  (out/'failure.json').write_text(json.dumps({'status':'failed','package_id':eid,'error':repr(exc),'checks':checks,'runs':runs},ensure_ascii=False,indent=2)+'\n');raise
if __name__=='__main__':main()
