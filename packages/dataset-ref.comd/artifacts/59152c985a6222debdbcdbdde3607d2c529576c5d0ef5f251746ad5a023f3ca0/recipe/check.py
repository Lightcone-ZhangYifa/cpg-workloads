#!/usr/bin/env python3
"""Run bounded installed-profile checks without network or modifying the prefix."""
from pathlib import Path
import argparse,hashlib,json,math,os,re,subprocess,tempfile,zlib

def main():
 p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);a=p.parse_args();root=a.prefix.resolve(strict=True);cfg=json.loads((Path(__file__).with_name('config.json')).read_text());name=cfg['name'];rows=[]
 env={**os.environ,'LC_ALL':'C','LD_LIBRARY_PATH':str(root/'lib')}
 with tempfile.TemporaryDirectory(prefix='cpg-native-check-') as temp:
  work=Path(temp)
  def run(label,args,*,input=None,allowed=(0,)):
   result=subprocess.run(list(map(str,args)),input=input,cwd=work,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=120)
   rows.append({'case':label,'returncode':result.returncode,'stdout_sha256':hashlib.sha256(result.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(result.stderr).hexdigest()})
   if result.returncode not in allowed:raise AssertionError(label+' failed: '+result.stderr.decode(errors='replace')[-2000:])
   return result
  if name!='comd':
   encoded=work/'encoded';result=run('installed-c-api',[root/'bin/cpg-native-check',encoded]);info=json.loads(result.stdout)
   if info['status']!='passed':raise AssertionError('C API did not pass')
   if name in {'zlib','libdeflate'}:
    clear=zlib.decompress(encoded.read_bytes());expected=bytes(((i*17+(i>>3))&255) for i in range(65536))
    if clear!=expected:raise AssertionError('Standard-library DEFLATE cross-check differs')
    rows.append({'case':'stdlib-zlib-cross-decode','status':'passed','bytes':len(clear),'independent_semantic_oracle_qualification':False})
   if name=='yyjson':
    parsed=json.loads(encoded.read_text())
    if parsed!={'name':'compiler-playground','n':42,'values':[True,None,-7,1.5]}:raise AssertionError('Python JSON cross-parse differs')
    rows.append({'case':'stdlib-json-cross-parse','status':'passed'})
   # Runtime library provenance is checked independently from return codes.
   linked=run('runtime-link-map',['ldd',root/'bin/cpg-native-check']);text=linked.stdout.decode()
   for basename in cfg['expected_shared_libraries']:
    line=next((line for line in text.splitlines() if basename in line and '=>' in line),None)
    if line is None or str(root/'lib') not in line:raise AssertionError('Selected shared library not resolved from installed prefix: '+basename)
   if name in {'libdeflate','lz4','brotli'}:
    data=bytes((i*29)%256 for i in range(8192));src=work/'in';src.write_bytes(data)
    if name=='libdeflate':comp=[root/'bin/libdeflate-gzip','-c',src];dec=[root/'bin/libdeflate-gzip','-d','-c',work/'data.gz']
    elif name=='lz4':comp=[root/'bin/lz4','-q','-c',src];dec=[root/'bin/lz4','-q','-d','-c',work/'data.gz']
    else:comp=[root/'bin/brotli','-c',src];dec=[root/'bin/brotli','-d','-c',work/'data.gz']
    (work/'data.gz').write_bytes(run('cli-compress',comp).stdout)
    if run('cli-decompress',dec).stdout!=data:raise AssertionError('CLI roundtrip differs')
  else:
   base=[root/'bin/CoMD-serial','-x','4','-y','4','-z','4','-N','10','-n','5']
   for label,extra in [('lennard-jones',[]),('eam-funcfl',['-e','-d',root/'share/comd/pots','-p','Cu_u6.eam','-t','funcfl'])]:
    text=run(label,base+extra).stdout.decode();match=re.search(r'Final atom count\s*:\s*256, no atoms lost',text)
    if not match:raise AssertionError('CoMD did not preserve the expected atom count')
    initial=float(re.search(r'Initial energy\s*:\s*(\S+)',text)[1].rstrip(','));final=float(re.search(r'Final energy\s*:\s*(\S+)',text)[1].rstrip(','))
    if not math.isfinite(initial+final) or abs(final-initial)>1e-3*max(1.,abs(initial)):raise AssertionError('CoMD bounded energy consistency check failed')
    rows.append({'case':label+'-consistency','initial_energy':initial,'final_energy':final,'atoms':256,'independent_semantic_oracle_qualification':False})
 print(json.dumps({'status':'passed','profile':name,'checks':rows,'formal_original_target_qualification':False,'official_benchmark':False},sort_keys=True))
if __name__=='__main__':main()
