import ctypes, hashlib, json, os, pathlib, re, subprocess, sys, time
R=pathlib.Path(__file__).resolve().parents[1]
B=pathlib.Path(os.environ.get('CPG_WORK_ROOT',str(R/'build')))/'orio';B.mkdir(parents=True,exist_ok=True)
orcc=R/'source/orio/scripts/orcc'
def run(cmd, name, timeout=120):
    p=subprocess.run([str(x) for x in cmd],cwd=B,capture_output=True,text=True,timeout=timeout)
    (B/(name+'.stdout')).write_text(p.stdout);(B/(name+'.stderr')).write_text(p.stderr)
    if p.returncode:
        raise RuntimeError(f'{name} failed: {p.returncode}: {p.stderr[-1500:]}')
    return p
function='''void add(int n,double*a,double*b,double*c) {
int i;
/*@ begin Loop(transform Unroll(ufactor=UF, parallelize=False)
for(i=0;i<=n-1;i++) c[i]=a[i]+b[i];
) @*/
for(i=0;i<=n-1;i++) c[i]=a[i]+b[i];
/*@ end @*/
}
'''
harness='''
#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
int main(void) {
 int n=262144; double*a=malloc(n*sizeof(double)),*b=malloc(n*sizeof(double)),*c=malloc(n*sizeof(double));
 if(!a||!b||!c)return 9;
 for(int i=0;i<n;i++){a[i]=i%101;b[i]=i%13;c[i]=0;}
 struct timespec x,y;clock_gettime(CLOCK_MONOTONIC,&x);
 for(int r=0;r<60;r++){add(n,a,b,c);__asm__ __volatile__("" : : "g"(c) : "memory");}
 clock_gettime(CLOCK_MONOTONIC,&y);double seconds=((y.tv_sec-x.tv_sec)+(y.tv_nsec-x.tv_nsec)*1e-9)/60;
 unsigned long long checksum=0;for(int i=0;i<n;i++){if(c[i]!=(double)(i%101+i%13))return 2;checksum+=(unsigned long long)c[i];}
 printf("{\\"seconds\\":%.17g,\\"checksum\\":%llu,\\"correct\\":true}\\n",seconds,checksum);
 free(a);free(b);free(c);return 0;
}
'''
rows=[]
for u in [2,4]:
    inp=B/f'annotated-u{u}.c';out=B/f'generated-u{u}.c'
    inp.write_text(function.replace('ufactor=UF','ufactor='+str(u)))
    run([sys.executable,'-S',orcc,'-o',out,inp],f'transform-{u}')
    generated=out.read_text()
    if f'i+{u-1}' not in generated.replace(' ',''):
        raise RuntimeError('Orio did not generate expected unrolled body')
    combined=B/f'checked-u{u}.c';combined.write_text(generated+harness)
    exe=B/f'u{u}'
    run(['gcc','-O2',combined,'-o',exe],f'compile-{u}')
    result=json.loads(run([exe],f'run-{u}').stdout)
    if not result['correct'] or result['seconds']<=0: raise RuntimeError('incorrect generated variant')
    rows.append(dict(result,unroll=u,source_sha256=hashlib.sha256(generated.encode()).hexdigest()))
best=min(rows,key=lambda x:x['seconds'])
replay=json.loads(run([B/f"u{best['unroll']}"],'best-replay').stdout)
if replay['checksum']!=best['checksum']:raise RuntimeError('replay differs')
spec='''/*@ begin PerfTuning (
def build {arg build_command='gcc -O2';}
def performance_counter {arg repetitions=3;}
def performance_params {param UF[]=[2,4];}
def input_params {param n[]=[262144];}
def input_vars {decl dynamic double a[n]=random;decl dynamic double b[n]=random;decl dynamic double c[n]=0;}
def search {arg algorithm='Exhaustive';}
) @*/
'''
tuning=function.replace('int i;','int i;\n'+spec).replace('\n}\n','\n/*@ end @*/\n}\n')
(B/'tuning.c').write_text(tuning)
native=run([sys.executable,'-S',orcc,'-v','-o',B/'tuned.c',B/'tuning.c'],'native-search',timeout=180)
if not (B/'tuned.c').exists():raise RuntimeError('native search did not emit tuned source')
report={'status':'pass','backend':'native_cpu','transforms':[2,4],'evaluated':rows,
        'best_unroll':best['unroll'],'best_replay':replay,'native_exhaustive_search':True,
        'correctness':'all elements checked for both transformed versions',
        'performance_claim':'bounded shared-host experiment; no general speedup claim'}
(pathlib.Path.cwd()/'orio-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
