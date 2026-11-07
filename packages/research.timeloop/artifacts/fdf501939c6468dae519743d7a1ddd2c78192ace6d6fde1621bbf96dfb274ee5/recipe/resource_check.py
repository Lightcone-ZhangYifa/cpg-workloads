#!/usr/bin/env python3
"""Fixed, offline Timeloop mapper-to-model acceptance; prefix stays read-only."""
import argparse, hashlib, json, math, os, re, resource, shutil, struct, subprocess, tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    p=a.prefix.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    w=Path(tempfile.mkdtemp(prefix='run-',dir=out));checks=[];commands=[]
    def need(v,n):
        if not v:raise RuntimeError(n)
        checks.append({'name':n,'status':'passed'})
    def static_elf(path):
        b=path.read_bytes();need(b[:6]==b'\x7fELF\x02\x01','ELF64 little-endian '+path.name)
        h=struct.unpack_from('<HHIQQQIHHHHHH',b,16);need(h[1]==62,'x86_64 '+path.name)
        tags=[struct.unpack_from('<I',b,h[4]+i*h[8])[0] for i in range(h[9])]
        need(2 not in tags and 3 not in tags,'no dynamic/interpreter dependency '+path.name)
    for n in ['timeloop-mapper','timeloop-model']:static_elf(p/'bin'/n)
    env={k:v for k,v in os.environ.items() if not k.startswith('LD_')}
    env.update(TIMELOOP_PROBLEM_SHAPE_DIR=str(p/'share/problem-shapes'),TIMELOOP_PROBLEM_SHAPE_DIRS=str(p/'share/problem-shapes'),OMP_NUM_THREADS='1',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1')
    cfg=w/'matmul.yaml';shutil.copy2(p/'fixtures/matmul.yaml',cfg)
    budget={'algorithm':'exhaustive','threads':1,'search_size':6,'victory_condition':100,'invalid_mapping_timeout':1000,'wall_timeout_seconds':45,'seed':None,'seed_reason':'deterministic exhaustive enumeration; no random search','mapspace_cardinality':6,'problem':{'M':4,'N':4,'K':4},'architecture':{'arithmetic_instances':1,'word_bits':16,'Buffer_entries':64,'DRAM':'analytical default'},'energy_model':'built-in Timeloop/PAT estimates; no calibrated ERT; no physical area claim'}
    (w/'search-budget.json').write_text(json.dumps(budget,indent=2))
    def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    def run(name,binary,inputs,positive=True):
        d=w/name;d.mkdir();cmd=[str(p/'bin'/binary),*map(str,inputs)]
        r=subprocess.run(cmd,cwd=d,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45,preexec_fn=no_core)
        (d/'console.log').write_text(r.stdout);commands.append({'name':name,'argv':cmd,'returncode':r.returncode})
        if (r.returncode==0)!=positive:raise RuntimeError(name+' unexpected exit status\n'+r.stdout[-5000:])
        need(True,name+' expected process exit');return d,r.stdout
    md,log=run('mapper','timeloop-mapper',[cfg])
    need('Using threads = 1' in log,'fixed single mapper thread')
    need('6 valid mappings found' in log,'full six-mapping bounded search completed')
    for dim,size in [('IndexFactorization',1),('LoopPermutation',6),('Spatial',1),('DatatypeBypass',1)]:
        need('Mapspace Dimension ['+dim+'] Size: '+str(size) in log,'recorded '+dim+' mapspace')
    mapping=md/'timeloop-mapper.map.yaml';need(mapping.is_file(),'mapper produced YAML mapping')
    txt=mapping.read_text();products={d:1 for d in 'MNK'}
    factors=re.findall(r'^\s*factors:\s*(.+)$',txt,re.M);need(len(factors)==2,'two temporal mapping levels')
    for f in factors:
        pairs=re.findall(r'([MNK])(\d+)',f);need(len(pairs)==3,'complete factor tuple')
        for d,v in pairs:products[d]*=int(v)
    need(products=={'M':4,'N':4,'K':4},'mapping factor products equal workload dimensions')
    for perm in re.findall(r'^\s*permutation:\s*(\S+)',txt,re.M):need(sorted(perm)==list('KMN'),'valid loop permutation')
    rd,rlog=run('model-replay','timeloop-model',[cfg,mapping])
    def costs(d,stem):
        sp=d/(stem+'.stats.txt');xp=d/(stem+'.map+stats.xml');need(sp.is_file() and xp.is_file(),stem+' text and XML costs present')
        text=sp.read_text();raw_xml=xp.read_text()
        try:tree=ET.ElementTree(ET.fromstring(raw_xml))
        except ET.ParseError:
            need(stem=='timeloop-model' and raw_xml.rstrip().endswith('</a>') and '<boost_serialization ' in raw_xml and '</boost_serialization>' not in raw_xml,'recognized upstream missing XML root closer only')
            normalized=raw_xml+'\n</boost_serialization>\n';tree=ET.ElementTree(ET.fromstring(normalized))
            np=d/(stem+'.map+stats.normalized.xml');np.write_text(normalized)
            (d/'xml-normalization.json').write_text(json.dumps({'original':xp.name,'original_sha256':hashlib.sha256(raw_xml.encode()).hexdigest(),'normalized':np.name,'change':'Append missing </boost_serialization> root closing tag only; no statistic or mapping data changed.','upstream_observation':'Official image source Model::Run takes xml_str.str() before xml_oarchive destructor emits final root closer.'},indent=2))
        arith=tree.find('.//levels_/item/px')
        computes=int(arith.findtext('algorithmic_computes_'));cycles=int(re.search(r'^Cycles:\s*(\d+)',text,re.M).group(1))
        energy=float(arith.findtext('energy_'))
        levels=[]
        for level in tree.findall('.//levels_/item/px'):
            stats=level.find('stats_')
            if stats is None:continue
            name=level.findtext('specs_/LevelSpecs/level_name');parts={}
            for tag in ['energy','temporal_reduction_energy','addr_gen_energy']:
                parts[tag]=sum(float(v.text) for v in stats.findall(tag+'/PerDataSpace/item'))
            level_energy=sum(parts.values());energy+=level_energy;levels.append({'name':name,'energy_pj':level_energy,'components_pj':parts})
        # All networks have zero modelled energy in this one-PE fixture. Refuse to silently omit a nonzero network.
        for node in tree.findall('.//networks_/item/second/px'):
            vals=[float(v.text) for tag in ['energy','spatial_reduction_energy','link_transfer_energy'] for v in node.findall('.//'+tag+'/PerDataSpace/item')]
            need(all(v==0 for v in vals),'zero network costs in single-PE fixture')
        fj=float(re.search(r'^\s+Total\s*=\s*([0-9.eE+-]+)',text,re.M).group(1))
        need(computes==64 and cycles==64,stem+' expected 64 MACs and cycles')
        need(energy>0 and math.isfinite(energy),stem+' finite positive model energy')
        need(math.isclose(energy/64*1000,fj,abs_tol=.011),stem+' full-precision XML agrees with text fJ/compute')
        return {'computes':computes,'cycles':cycles,'energy_pj':energy,'pj_per_compute':energy/64,'levels':levels,'arithmetic_energy_pj':float(arith.findtext('energy_'))}
    mc=costs(md,'timeloop-mapper');rc=costs(rd,'timeloop-model')
    for key in ['computes','cycles','energy_pj','pj_per_compute']:need(math.isclose(mc[key],rc[key],rel_tol=1e-12),key+' identical in mapper and model replay')
    bad=w/'invalid-mapping.yaml';need('M4 N4 K4' in txt,'negative case has expected mapping anchor');bad.write_text(txt.replace('M4 N4 K4','M3 N4 K4',1))
    nd,nlog=run('negative-factor-mismatch','timeloop-model',[cfg,bad],False)
    need('product of all factors of dimension M is 3' in nlog and 'workload 4' in nlog,'negative rejected for exact dimension mismatch')
    (w/'cost-comparison.json').write_text(json.dumps({'mapper':mc,'model':rc,'physical_measurement':False,'sparse_capability_qualified':False},indent=2));(w/'commands.json').write_text(json.dumps(commands,indent=2))
    files=[str(f.relative_to(out)) for f in sorted(w.rglob('*')) if f.is_file()]
    result={'status':'passed','resource':'research.timeloop','checks':checks,'metrics':mc,'search_budget':budget,'evidence_files':files,'limitations':['Dense 4x4x4 GEMM only; sparse/Sparseloop capabilities are not claimed by this test.','Energy is a built-in analytical estimate; no hardware measurement or area validation.','Official OCI prebuilt binaries, independently pinned by image/layer/binary hashes; no local source-build claim.']}
    (out/'result.json').write_text(json.dumps(result,indent=2));print('CPG_CHECK_PASS research.timeloop')
if __name__=='__main__':main()
