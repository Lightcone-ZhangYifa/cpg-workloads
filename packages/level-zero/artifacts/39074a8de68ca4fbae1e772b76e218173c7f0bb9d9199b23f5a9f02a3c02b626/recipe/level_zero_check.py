#!/usr/bin/env python3
from pathlib import Path
import argparse,subprocess,tempfile,json,os,hashlib,re
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.prefix=a.prefix.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
env={k:v for k,v in os.environ.items() if not k.startswith(('ZE_','ZEL_')) and k!='LD_PRELOAD'};env['LD_LIBRARY_PATH']=str(a.prefix/'lib')
checks=[]
with tempfile.TemporaryDirectory(prefix='cpg-l0-',dir=a.output) as t:
 t=Path(t)
 for lang,cc,std in [('c','gcc','c11'),('cpp','g++','c++17')]:
  s=t/('consumer.'+lang);s.write_text('#include <level_zero/ze_api.h>\n#include <level_zero/ze_ddi.h>\n#include <level_zero/zes_api.h>\n#include <level_zero/zet_api.h>\nint main(void){ze_init_driver_type_desc_t x={};x.stype=ZE_STRUCTURE_TYPE_INIT_DRIVER_TYPE_DESC;return sizeof(x)+sizeof(&zeInitDrivers)==0;}\n')
  cmd=[cc,'-std='+std,'-I'+str(a.prefix/'include'),'-fsyntax-only',str(s)];r=subprocess.run(cmd,capture_output=True,text=True,timeout=60);checks.append({'case':lang+'_schema_consumer','argv':cmd,'returncode':r.returncode,'stderr':r.stderr});
  if r.returncode:raise RuntimeError(r.stderr)
  s.write_text('#include <level_zero/ze_api.h>\nint main(void){return ZE_STRUCTURE_TYPE_NOT_A_REAL_SCHEMA;}\n');r=subprocess.run(cmd,capture_output=True,text=True,timeout=60);checks.append({'case':lang+'_undefined_schema_negative','argv':cmd,'returncode':r.returncode,'stderr':r.stderr})
  if r.returncode==0 or 'ZE_STRUCTURE_TYPE_NOT_A_REAL_SCHEMA' not in r.stderr:raise RuntimeError('bad schema accepted')
 r=subprocess.run([str(a.prefix/'bin/cpg-level-zero-probe')],env=env,capture_output=True,text=True,timeout=120)
 if r.returncode:raise RuntimeError('loader probe failed '+str(r.returncode)+': '+r.stderr)
 observed=json.loads(r.stdout)
 if Path(observed['loader_path']).resolve()!=(a.prefix/'lib/libze_loader.so.1').resolve():raise RuntimeError('unexpected Level Zero loader')
 if observed['loader_version']!='1.34.0' or observed['device_execution_qualified'] is not False:raise RuntimeError('invalid loader qualification')
 observed.update(scope='Official headers/schema and loader only. No vendor driver is included; initialization observation never qualifies device execution. Tracing/validation layers and null driver are not packaged.',checks=checks,stderr=r.stderr,hardware_status='driver_unavailable' if observed['drivers']==0 else 'driver_observed_execution_not_tested')
 (a.output/'result.json').write_text(json.dumps(observed,indent=2)+'\n');print(json.dumps({k:v for k,v in observed.items() if k not in ('checks','stderr')}))
