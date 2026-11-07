#!/usr/bin/env python3
"""Offline prefix-read-only Accelergy acceptance: upstream microarchitecture and CACTI."""
import argparse,hashlib,json,math,os,shutil,subprocess,sys,tempfile
from pathlib import Path

def main():
    a=argparse.ArgumentParser();a.add_argument('--prefix',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--synthetic-only',action='store_true');args=a.parse_args()
    p=args.prefix.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='run-',dir=out));sys.path.insert(0,str(p/'python'));import yaml
    checks=[];commands=[]
    def need(ok,name):
        if not ok:raise RuntimeError(name)
        checks.append({'name':name,'status':'passed'})
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1');env.pop('PYTHONPATH',None)
    def run(name,inputs,plugins,ok=True):
        d=work/name;d.mkdir()
        cfg={'version':0.4,'estimator_plug_ins':[str(p/'plugins/dummy')]+[str(x.parent) for x in plugins if x.suffix=='.yaml'],'primitive_components':[str(p/'primitive-components')],'compound_components':[],'math_functions':[],'python_plug_ins':[str(x) for x in plugins if x.suffix=='.py'],'table_plug_ins':{'roots':[]}}
        (d/'accelergy_config.yaml').write_text(yaml.safe_dump(cfg))
        cmd=[sys.executable,'-I','-S','-B','-c','import sys,builtins;builtins.exit=sys.exit;sys.path.insert(0,sys.argv.pop(1));from accelergy.accelergy_console import main;main()',str(p/'python'),*map(str,inputs),'-o',str(d),'-v','1']
        r=subprocess.run(cmd,cwd=d,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
        (d/'console.log').write_text(r.stdout);commands.append({'name':name,'argv':cmd,'returncode':r.returncode})
        if (r.returncode==0)!=ok: raise RuntimeError(name+' expected exit status; '+r.stdout[-3000:])
        need(True,name+' expected exit status')
        if ok:
            for fn in ['ERT.yaml','ART.yaml','energy_estimation.yaml']:need((d/fn).is_file(),name+' produced '+fn)
        return d
    original=p/'fixtures/official_micro';fixture=work/'official-micro-v04';fixture.mkdir()
    for fn in ['arch.yaml','components.yaml']:
        text=(original/fn).read_text().replace('area_share','area_scale').replace('action_share','energy_scale')
        (fixture/fn).write_text(text)
    shutil.copy2(original/'plugins.py',fixture/'plugins.py')
    original_hashes={fn:hashlib.sha256((original/fn).read_bytes()).hexdigest() for fn in ['arch.yaml','components.yaml','plugins.py']}
    arch=yaml.safe_load((fixture/'arch.yaml').read_text())
    locals_=arch['architecture']['subtree'][0]['local'];moves=[]
    for component in locals_:
        attributes=component.get('attributes',{})
        if 'area_scale' in attributes:
            if 'area_scale' in component:raise RuntimeError('Ambiguous architecture scale migration: '+component['name'])
            value=attributes.pop('area_scale');component['area_scale']=value
            moves.append({'component':component['name'],'source':'attributes.area_share (renamed attributes.area_scale)','destination':'area_scale beside attributes','value':value})
    need(len(moves)==4 and [x['value'] for x in moves]==[2,3,4,5],'four deprecated architecture scales moved to supported sibling fields')
    (fixture/'arch.yaml').write_text(yaml.safe_dump(arch,sort_keys=False))
    migration={'upstream_original':'fixtures/official_micro','original_sha256':original_hashes,
        'key_renames':{'area_share':'area_scale','action_share':'energy_scale'},'architecture_scale_relocations':moves,
        'reason':'Pinned ArchComp initializes a sibling area_scale=1 and reads it before attributes; moving the four deprecated architecture attribute scales preserves their intended scaling in the supported interface.',
        'source_rules':['python/accelergy/arch_dict_2_obj.py:ArchComp.__init__/get_area_scale','python/accelergy/raw_inputs_2_dicts.py:compound subcomponent area_scale normalization'],
        'scope':'Only generated input copies are adapted. Official originals and all upstream implementation code remain unchanged. Compound subcomponent attribute scales already supported by the pinned parser are unchanged.'}
    (fixture/'migration.json').write_text(json.dumps(migration,indent=2))
    names=['arch.'+c['name'] for c in arch['architecture']['subtree'][0]['local']]
    counts={'action_counts':{'version':0.4,'local':[{'name':n,'action_counts':[{'name':'read','counts':3},{'name':'write','counts':2}]} for n in names]}}
    cp=work/'official-action-counts.yaml';cp.write_text(yaml.safe_dump(counts,sort_keys=False))
    # Independent arithmetic oracle: the official primitive returns 1 pJ and 1 um2.
    # Class action multipliers are 8,4,2 (read) and .5,.5,.5 (write).
    # Class area multipliers are 2,3,4. Architecture area scales do not scale energy.
    bases={'three_level_hierarchy':(1*8*4*2,1*.5*.5*.5,1*2*3*4),
           'two_level_hierarchy':(1*8*4,1*.5*.5,1*2*3),
           'one_level_hierarchy':(1*8,1*.5,1*2),'primitive_direct_from_arch':(1,1,1)}
    expected=dict(bases);expected['two_subcomponents_different_shares']=(1*8+1*4,1*.5+1*.25,1*2+1*3)
    scale_cases={}
    for (base,(read,write,area)),migrated_scale,sibling_scale in zip(bases.items(),[2,3,4,5],[6,7,8,9]):
        for suffix,scale in [('_with_area_scale',migrated_scale),('_with_area_scale_defined_not_in_attrs',sibling_scale)]:
            expected[base+suffix]=(read,write,area*scale);scale_cases[base+suffix]=scale
    need(len(names)==13 and set(names)=={'arch.'+n for n in expected},'all thirteen official components match the independent oracle')
    local_by_name={x['name']:x for x in locals_}
    need(all(local_by_name[n].get('area_scale')==v and 'area_scale' not in local_by_name[n]['attributes'] for n,v in scale_cases.items()),'all eight architecture scale variants use their declared supported multipliers')
    expected_total=sum(3*read+2*write for read,write,area in expected.values())
    oracle={'method':'Scalar formulas from the fixed official primitive/component definitions; no expected value is read from generated ERT/ART.',
        'unit_primitive':{'read_pj':1,'write_pj':1,'area_um2':1},
        'base_formulas':{'three_level_hierarchy':['1*8*4*2','1*0.5*0.5*0.5','1*2*3*4'],'two_level_hierarchy':['1*8*4','1*0.5*0.5','1*2*3'],'one_level_hierarchy':['1*8','1*0.5','1*2'],'primitive_direct_from_arch':['1','1','1'],'two_subcomponents_different_shares':['1*8+1*4','1*0.5+1*0.25','1*2+1*3']},
        'variant_rule':'read and write unchanged; area equals the class base area times the explicit architecture sibling area_scale after documented migration',
        'architecture_area_scales':scale_cases,'expected':{n:{'read_pj':v[0],'write_pj':v[1],'area_um2':v[2]} for n,v in expected.items()},
        'action_counts_per_component':{'read':3,'write':2},'expected_total_pj':expected_total,'source_fixture_sha256':original_hashes}
    (work/'independent-oracle.json').write_text(json.dumps(oracle,indent=2))
    d=run('official-synthetic',[fixture/'arch.yaml',fixture/'components.yaml',cp],[fixture/'plugins.py'])
    ert=yaml.safe_load((d/'ERT.yaml').read_text())['ERT']['tables'];art=yaml.safe_load((d/'ART.yaml').read_text())['ART']['tables']
    vals={t['name']:{a['name']:a['energy'] for a in t['actions']} for t in ert};areas={t['name']:t['area'] for t in art}
    need(len(ert)==13 and len(art)==13 and set(vals)==set(names) and set(areas)==set(names),'ERT and ART cover exactly all thirteen components')
    for n,(rd,wr,ar) in expected.items():
        k='arch.'+n
        for actual,want,tag in [(vals[k]['read'],rd,'read pJ'),(vals[k]['write'],wr,'write pJ'),(areas[k],ar,'area um2')]:need(math.isclose(actual,want,rel_tol=1e-9,abs_tol=1e-9),k+' '+tag)
    total=sum(3*vals[n]['read']+2*vals[n]['write'] for n in names)
    reported=yaml.safe_load((d/'energy_estimation.yaml').read_text())['energy_estimation']['Total'];need(math.isclose(total,reported,rel_tol=1e-9),'independently recomputed official microarchitecture energy')
    need(math.isclose(reported,expected_total,rel_tol=1e-9),'reported energy equals independent thirteen-component formula total')
    bad=json.loads(json.dumps(counts));bad['action_counts']['local'][0]['action_counts'][0]['name']='nonexistent_action';bp=work/'invalid-action-counts.yaml';bp.write_text(yaml.safe_dump(bad))
    nd=run('negative-unknown-action',[fixture/'arch.yaml',fixture/'components.yaml',bp],[fixture/'plugins.py'],False)
    diagnostic=(nd/'console.log').read_text();required_diagnostics=["KeyError: 'nonexistent_action'",'get_action_energy','energy_calculator.py']
    need(all(x in diagnostic for x in required_diagnostics),'negative rejected specifically by ERT lookup of nonexistent_action')
    (nd/'negative-diagnostic.json').write_text(json.dumps({'expected_exception':'KeyError','unknown_action':'nonexistent_action','required_diagnostics':required_diagnostics,'returncode':commands[-1]['returncode'],'status':'passed'},indent=2))
    models=[{'profile':'official-synthetic','estimator':'upstream DummyObjectAreaEnergyOne','physical_credibility':False,'energy_pj':reported,'component_count':len(names)}]
    if not args.synthetic_only:
        plugin=work/'cacti-plugin';shutil.copytree(p/'plugins/cacti',plugin);need((plugin/'cacti').is_file(),'bundled CACTI binary')
        sa={'architecture':{'version':0.4,'subtree':[{'name':'tutorial_sram','attributes':{'technology':45,'global_cycle_seconds':1e-9},'local':[{'name':'GLB','class':'SRAM','attributes':{'width':32,'depth':1024,'n_rw_ports':2,'n_banks':1}}]}]}}
        sc={'action_counts':{'version':0.4,'local':[{'name':'tutorial_sram.GLB','action_counts':[{'name':'read','counts':7},{'name':'write','counts':5}]}]}}
        sap=work/'tutorial-sram.yaml';scp=work/'tutorial-sram-counts.yaml';sap.write_text(yaml.safe_dump(sa));scp.write_text(yaml.safe_dump(sc))
        d=run('cacti-real-model',[sap,scp],[plugin/'cacti.estimator.yaml'])
        ce=yaml.safe_load((d/'ERT.yaml').read_text())['ERT']['tables'][0];cv={a['name']:a['energy'] for a in ce['actions']};ca=yaml.safe_load((d/'ART.yaml').read_text())['ART']['tables'][0]['area'];ct=yaml.safe_load((d/'energy_estimation.yaml').read_text())['energy_estimation']['Total']
        for k in ['read','write']:need(math.isfinite(cv[k]) and cv[k]>0 and cv[k]!=1,'CACTI '+k+' positive non-placeholder pJ')
        need(math.isfinite(ca) and ca>1,'CACTI positive non-placeholder area');need(math.isclose(ct,7*cv['read']+5*cv['write'],rel_tol=1e-5),'CACTI action count aggregation')
        models.append({'profile':'cacti-real-model','estimator':'HewlettPackard CACTI 7.0 via official Accelergy plugin','physical_measurement':False,'physical_credibility':'analytical model only, no target-chip calibration','read_pj':cv['read'],'write_pj':cv['write'],'area_um2':ca,'energy_pj':ct})
    need(all(hashlib.sha256((original/fn).read_bytes()).hexdigest()==digest for fn,digest in original_hashes.items()),'official original fixture files remain unchanged')
    (work/'commands.json').write_text(json.dumps(commands,indent=2))
    files=[str(x.relative_to(out)) for x in sorted(work.rglob('*')) if x.is_file() and x.suffix in {'.yaml','.json','.log','.txt','.cfg'}]
    result={'status':'passed' if not args.synthetic_only else 'development_synthetic_only','resource':'research.accelergy','checks':checks,'models':models,'evidence_files':files,'limitations':['Synthetic fixture has no physical meaning.','CACTI results are analytical estimates, not measured power.','Linux x86_64 CPython 3.12 runtime.']}
    (out/'result.json').write_text(json.dumps(result,indent=2));print('CPG_CHECK_PASS research.accelergy' if not args.synthetic_only else 'CPG_SYNTHETIC_DIAGNOSTIC_PASS')
if __name__=='__main__':main()
