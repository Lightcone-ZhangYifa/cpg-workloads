#!/usr/bin/env python3
"""Resume static intake of explicitly named CPG ZIP members; never run workloads."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from import_archives import import_package, safe_relative, sha256, write_json


def identity(manifest, digest, size):
    spec=manifest['package']
    return {'id':spec['id'],'version':spec['version'],'build':spec['build'],
            'target':spec['target'],'method':manifest['method'],'sha256':digest,
            'bytes':size,'manifest_sha256':manifest['manifest_sha256']}


def candidate_jobs(ledger, history, parts_reader):
    for row in ledger['files']:
        idx=ledger['zip_indexes'].get(row.get('zip_index_key'),{})
        for member in idx.get('cpg_name_leads',[]):
            yield {'kind':'file','source':row['path'],'source_sha256':row['sha256'],
                   'source_bytes':row['bytes'],'member':member['path'],'member_bytes':member['bytes'],
                   'unsafe_container':bool(idx.get('duplicate_names') or idx.get('unsafe_names'))}
    for family in ledger['split_families']:
        idx=ledger['zip_indexes'].get(family.get('zip_index_key'),{})
        for member in idx.get('cpg_name_leads',[]):
            yield {'kind':'split','source':family['family'],'parts':family['parts'],
                   'member':member['path'],'member_bytes':member['bytes'],
                   'unsafe_container':bool(idx.get('duplicate_names') or idx.get('unsafe_names'))}
    for row in ledger['files']:
        name=Path(row['path']).name.lower()
        named=name.endswith(('.cpgpkg','.cpgpkg.tar.gz','.cpgrecipe.tar.gz'))
        if named or row.get('known_artifact_identity') or row.get('known_raw_source_lock'):
            job={'kind':'standalone','source':row['path'],'source_sha256':row['sha256'],
                   'source_bytes':row['bytes'],'member':Path(row['path']).name,'member_bytes':row['bytes'],
                   'unsafe_container':False}
            if row.get('known_raw_source_lock') and not (named or row.get('known_artifact_identity')):
                job.update(expected_sha256=row['sha256'],lead_role='raw_source')
            elif row.get('known_online_recipe'):
                job['lead_role']='online_recipe'
            yield job
    for row in ledger['files']:
        idx=ledger['zip_indexes'].get(row.get('zip_index_key'),{})
        for member in idx.get('known_object_leads',[]):
            yield {'kind':'file','source':row['path'],'source_sha256':row['sha256'],'source_bytes':row['bytes'],
                   'member':member['path'],'member_bytes':member['bytes'],'expected_sha256':member['sha256'],
                   'lead_role':member['role'],'unsafe_container':bool(idx.get('duplicate_names') or idx.get('unsafe_names'))}
    for family in ledger['split_families']:
        idx=ledger['zip_indexes'].get(family.get('zip_index_key'),{})
        for member in idx.get('known_object_leads',[]):
            yield {'kind':'split','source':family['family'],'parts':family['parts'],'member':member['path'],
                   'member_bytes':member['bytes'],'expected_sha256':member['sha256'],'lead_role':member['role'],
                   'unsafe_container':bool(idx.get('duplicate_names') or idx.get('unsafe_names'))}


def check_template(template):
    """Defer questionable authored input to manual review, retaining its cold package."""
    for path in template.rglob('*'):
        if path.is_symlink(): return 'authored_symlink_requires_review'
        if not path.is_file(): continue
        if path.name in ('manifest.json','package.json','authored-inputs.json'): continue
        relative=path.relative_to(template).parts
        if ('materials' in relative and path.suffix.lower() not in {'.json','.opam'}
                and not path.name.lower().startswith(('license','copying','notice'))):
            return 'authored_source_projection_requires_review'
        if path.stat().st_size > 1024*1024: return 'large_authored_file_requires_review'
        if path.name.lower().endswith(('.gz','.xz','.tbz','.bz2','.zip','.whl','.deb','.a','.so','.g4')):
            return 'authored_payload_requires_review'
        if b'\0' in path.read_bytes(): return 'binary_authored_file_requires_review'
    return None


def worker_labeled_id(identifier):
    return 'worker' in identifier.lower() or 'reference-pack' in identifier.lower()


def verified_case_jobs(ledger, cases):
    files={x['path']:x for x in ledger['files']};families={x['family']:x for x in ledger['split_families']}
    for case in cases:
        if case.get('status')!='verified_member_format_identified' or case.get('format')!='cpg_package':continue
        source=case['source'];base={'source':source,'member':case['member'],'member_bytes':case['bytes'],
            'expected_sha256':case['sha256_from_name'],'lead_role':'artifact','unsafe_container':False}
        if source in files:
            row=files[source];base.update(kind='file',source_sha256=row['sha256'],source_bytes=row['bytes'])
        else:
            base.update(kind='split',parts=families[source]['parts'])
        yield base


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger',type=Path,required=True);p.add_argument('--history-root',type=Path,required=True)
    p.add_argument('--framework-root',type=Path,required=True);p.add_argument('--workloads-root',type=Path,required=True)
    p.add_argument('--cold-root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True);p.add_argument('--limit',type=int,default=None)
    p.add_argument('--case-table',type=Path,help='Include verified CPG packages discovered in object cases')
    p.add_argument('--retry', choices=('apt','recipes','evidence','fixtures','cold-alias'), help='Revisit only the specified recorded deferrals')
    a=p.parse_args(); history=a.history_root.resolve(); root=a.workloads_root.resolve(); scratch=a.scratch.resolve()
    for dest in (a.state.resolve(),scratch,a.cold_root.resolve()):
        if dest.is_relative_to(history):p.error('Output must be outside historical input')
    sys.path.insert(0,str(a.framework_root.resolve()/'src'))
    from compiler_playground.packages import verify_package
    spec=importlib.util.spec_from_file_location('history_inventory',a.framework_root/'tools/history-inventory.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    raw=a.ledger.read_bytes(); ledger=json.loads(raw); ledger_sha=hashlib.sha256(raw).hexdigest()
    if a.state.exists():
        state=json.loads(a.state.read_text())
        if state['inventory_sha256']!=ledger['inventory_sha256']:p.error('Inventory identity changed')
    else:state={'schema_version':1,'inventory_sha256':ledger['inventory_sha256'],'results':{}}
    state['ledger_sha256']=ledger_sha
    rows={Path(r['path']).name:r for r in ledger['files']}
    scratch.mkdir(parents=True,exist_ok=True);cold=a.cold_root/'packages/sha256';cold.mkdir(parents=True,exist_ok=True)
    processed=0; verified_outer=set(); verified_splits={}; verified_cold=set()
    case_jobs=[]
    if a.case_table:
        case_table=json.loads(a.case_table.read_text())
        if case_table['inventory_sha256']!=ledger['inventory_sha256']:p.error('Case inventory identity differs')
        case_jobs=verified_case_jobs(ledger,case_table['cases'])
    for job in itertools.chain(candidate_jobs(ledger,history,module.PartsReader),case_jobs):
        key=hashlib.sha256(json.dumps(job,sort_keys=True).encode()).hexdigest()
        if key in state['results']:
            previous=state['results'][key]
            if previous['status']=='started':
                raise RuntimeError('A previous intake operation has an unknown outcome; inspect state before resuming')
            eligible_retry = (a.retry=='apt' and previous['status']=='held_apt_wrapper_import_would_rebuild') or (
                a.retry=='recipes' and previous['status']=='error' and '.cpgrecipe' in job['member'].lower()) or (
                a.retry=='evidence' and previous['status']=='error' and job['member'].lower().endswith('.preparation.json')) or (
                a.retry=='fixtures' and previous['status']=='error' and job['member'].endswith('/deliberately-truncated.cpgpkg')) or (
                a.retry=='cold-alias' and previous['status']=='known_object_name_matches_verified_cold_member_unverified')
            if not eligible_retry:continue
        elif a.retry:
            continue
        else:
            previous=None
        if a.limit is not None and processed>=a.limit:break
        processed+=1; outcome={'job':job,'status':'started'}
        if previous: outcome['previous_outcome']={k:v for k,v in previous.items() if k!='job'}
        state['results'][key]=outcome;write_json(a.state,state)
        # 'started' survives interruption; the driver must not assume an unknown operation completed.
        try:
            if job['unsafe_container']:raise ValueError('Outer ZIP has duplicate or unsafe paths')
            if job['kind'] in ('file','standalone'):
                rel=safe_relative(job['source']);source=history.joinpath(*rel.parts)
                if source.stat().st_size!=job['source_bytes']:raise ValueError('Outer size changed')
                if (source,job['source_sha256']) not in verified_outer:
                    if sha256(source)!=job['source_sha256']:raise ValueError('Outer SHA-256 changed')
                    verified_outer.add((source,job['source_sha256']))
                origin={'archive':source.name,'sha256':job['source_sha256'],'bytes':job['source_bytes']}
                if job['kind']=='file':origin['member']=job['member']
                zsource=source
            else:
                if job['source'] not in verified_splits:
                    parts=[]; h=hashlib.sha256(); n=0
                    for name in job['parts']:
                        row=rows[name];rel=safe_relative(row['path']);part=history.joinpath(*rel.parts)
                        if part.stat().st_size!=row['bytes']:raise ValueError('Split part size changed')
                        part_hash=hashlib.sha256()
                        with part.open('rb') as s:
                            for block in iter(lambda:s.read(1024*1024),b''):
                                h.update(block);part_hash.update(block);n+=len(block)
                        if part_hash.hexdigest()!=row['sha256']:raise ValueError('Split part SHA-256 changed')
                        parts.append(part)
                    verified_splits[job['source']]=(parts,h.hexdigest(),n)
                parts,full_sha,n=verified_splits[job['source']]
                origin={'archive':job['source'],'sha256':full_sha,'bytes':n,'member':job['member']}
                zsource=module.PartsReader(parts)
            safe_relative(job['member'])
            if a.retry=='cold-alias':
                digest=job['expected_sha256'];role=job.get('lead_role')
                candidate=(a.cold_root/'objects/sha256'/digest if role=='raw_source' else
                    a.cold_root/'recipes/sha256'/(digest+'.cpgrecipe.tar.gz') if role=='online_recipe' else
                    cold/(digest+'.cpgpkg.tar.gz'))
                if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size!=job['member_bytes']:
                    raise ValueError('Existing cold object size differs')
                if digest not in verified_cold:
                    if sha256(candidate)!=digest:raise ValueError('Existing cold object SHA-256 differs')
                    verified_cold.add(digest)
                h=hashlib.sha256();count=0
                if job['kind']=='standalone':
                    with source.open('rb') as inp:
                        for block in iter(lambda:inp.read(1024*1024),b''):h.update(block);count+=len(block)
                else:
                    with zipfile.ZipFile(zsource) as z:
                        info=z.getinfo(job['member'])
                        if info.file_size!=job['member_bytes']:raise ValueError('ZIP member size changed')
                        with z.open(info) as inp:
                            for block in iter(lambda:inp.read(1024*1024),b''):h.update(block);count+=len(block)
                if h.hexdigest()!=digest or count!=job['member_bytes']:raise ValueError('Duplicate member SHA-256 or size differs')
                record_path=root/'catalog/artifacts'/(digest+'.json')
                if role in ('artifact','online_recipe') and record_path.exists():
                    record=json.loads(record_path.read_text())
                    if record.get('sha256')!=digest or record.get('bytes')!=count:raise ValueError('Catalog identity conflict')
                    if origin not in record['origins']:record['origins'].append(origin);write_json(record_path,record)
                outcome.update(status='cold_alias_member_sha_verified',member_sha256=digest)
                write_json(a.state,state)
                print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                continue
            if job.get('expected_sha256'):
                digest=job['expected_sha256'];role=job.get('lead_role')
                candidate=(a.cold_root/'objects/sha256'/digest if role=='raw_source' else
                    a.cold_root/'recipes/sha256'/(digest+'.cpgrecipe.tar.gz') if role=='online_recipe' else
                    cold/(digest+'.cpgpkg.tar.gz'))
                if candidate.exists():
                    if candidate.is_symlink() or candidate.stat().st_size!=job['member_bytes']:
                        raise ValueError('Existing cold object size differs')
                    if digest not in verified_cold:
                        if sha256(candidate)!=digest:raise ValueError('Existing cold object SHA-256 differs')
                        verified_cold.add(digest)
                    outcome.update(status='known_object_name_matches_verified_cold_member_unverified',
                                   member_sha256_declared=digest)
                    write_json(a.state,state)
                    print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                    continue
            if job['member_bytes']>shutil.disk_usage(scratch).free:raise ValueError('Insufficient scratch space')
            with tempfile.TemporaryDirectory(prefix='intake-',dir=scratch) as temp:
                tmp=Path(temp);member=tmp/'member.cpgpkg'
                if job['kind']=='standalone':
                    with source.open('rb') as inp,member.open('xb') as out:shutil.copyfileobj(inp,out)
                else:
                    with zipfile.ZipFile(zsource) as z:
                        info=z.getinfo(job['member'])
                        if info.file_size!=job['member_bytes']:raise ValueError('ZIP member size changed')
                        with z.open(info) as inp,member.open('xb') as out:shutil.copyfileobj(inp,out)
                if job.get('expected_sha256') and sha256(member)!=job['expected_sha256']:
                    raise ValueError('Content-addressed member SHA-256 mismatch')
                if job.get('lead_role')=='raw_source':
                    digest=job['expected_sha256'];rawdir=a.cold_root/'objects/sha256';rawdir.mkdir(parents=True,exist_ok=True)
                    obj=rawdir/digest
                    if not obj.exists():
                        with member.open('rb') as inp,obj.open('xb') as out:shutil.copyfileobj(inp,out)
                    if obj.is_symlink() or obj.stat().st_size!=job['member_bytes'] or sha256(obj)!=digest:
                        raise ValueError('Cold raw source identity mismatch')
                    outcome.update(status='locked_raw_source_retained',member_sha256=digest,cold_path='objects/sha256/'+digest)
                    write_json(a.state,state)
                    print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                    continue
                if job['member'].endswith('/deliberately-truncated.cpgpkg'):
                    outcome['member_sha256']=sha256(member)
                if job['member'].lower().endswith('.preparation.json'):
                    evidence=json.loads(member.read_text())
                    if not isinstance(evidence,dict):raise ValueError('Preparation evidence must be a JSON object')
                    outcome.update(status='preparation_metadata_retained_in_original',member_sha256=sha256(member))
                    write_json(a.state,state)
                    print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                    continue
                if '.cpgrecipe' in job['member'].lower() or job.get('lead_role')=='online_recipe':
                    recipe_sha=sha256(member)
                    plan=root/'catalog/acquisition-plans'/(recipe_sha+'.json')
                    if plan.is_file():
                        known=json.loads(plan.read_text())
                        if known.get('sha256')!=recipe_sha or known.get('bytes')!=member.stat().st_size:
                            raise ValueError('Acquisition plan identity conflict')
                        outcome.update(status='known_acquisition_plan_deferred',member_sha256=recipe_sha,
                                       id=known.get('id'),catalog_reference=plan.relative_to(root).as_posix())
                        write_json(a.state,state)
                        print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                        continue
                    from online_recipe import import_recipe
                    staged=tmp/'staged';record=import_recipe(member,staged,origin)
                    digest=record['sha256'];size=record['bytes'];outcome.update(artifact_sha256=digest,
                        id=record['id'],method='online-recipe')
                    recipes=a.cold_root/'recipes/sha256';recipes.mkdir(parents=True,exist_ok=True)
                    obj=recipes/(digest+'.cpgrecipe.tar.gz')
                    if not obj.exists():
                        with member.open('rb') as inp,obj.open('xb') as out:shutil.copyfileobj(inp,out)
                    if obj.is_symlink() or obj.stat().st_size!=size or sha256(obj)!=digest:raise ValueError('Cold recipe identity mismatch')
                    outcome['cold_path']='recipes/sha256/'+obj.name
                    existing=root/'catalog/artifacts'/(digest+'.json')
                    if existing.exists():
                        old=json.loads(existing.read_text())
                        if any(old.get(k)!=record.get(k) for k in ('id','version','build','target','method','sha256','bytes')):
                            raise ValueError('Existing recipe identity conflict')
                        if origin not in old['origins']:old['origins'].append(origin);write_json(existing,old)
                        outcome['status']='existing_recipe_origin_recorded'
                    else:
                        template=staged/record['template'];hold=check_template(template);dest=root/record['template']
                        if hold:outcome['status']=hold
                        elif dest.exists():outcome['status']='held_existing_template_without_record'
                        else:
                            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(template,dest,symlinks=True)
                            write_json(existing,record);outcome.update(status='new_recipe_recorded',release_eligible=record['release_eligible'])
                    write_json(a.state,state)
                    print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
                    continue
                checked=verify_package(member); manifest=checked['manifest'];digest=checked['sha256'];size=checked['bytes']
                obj=cold/(digest+'.cpgpkg.tar.gz')
                if not obj.exists():
                    with member.open('rb') as inp,obj.open('xb') as out:shutil.copyfileobj(inp,out)
                if obj.is_symlink() or obj.stat().st_size!=size or sha256(obj)!=digest:raise ValueError('Cold mirror identity mismatch')
                outcome.update(artifact_sha256=digest,id=manifest['package']['id'],method=manifest['method'],cold_path='packages/sha256/'+obj.name)
                existing=root/'catalog/artifacts'/(digest+'.json')
                if existing.exists():
                    record=json.loads(existing.read_text())
                    if any(record.get(k)!=v for k,v in identity(manifest,digest,size).items()):raise ValueError('Existing identity conflict')
                    if origin not in record['origins']:
                        record['origins'].append(origin);write_json(existing,record)
                    outcome['status']='existing_artifact_origin_recorded'
                else:
                    staged=tmp/'staged';import_package(member,staged,origin,static_trust=True)
                    record=json.loads((staged/'catalog/artifacts'/(digest+'.json')).read_text())
                    if manifest['method']=='wrapper' and manifest['package']['provider']=='apt':
                        record['build_check_scope']='Deterministic metadata-only package repack; underlying APT installation was not run.'
                    template=staged/record['template'];hold=check_template(template)
                    dest=root/record['template']
                    if worker_labeled_id(record['id']):
                        identity_hold=scratch/'identity-holds'/digest
                        if identity_hold.exists():raise ValueError('Identity hold already exists; inspect before retry')
                        identity_hold.mkdir(parents=True);shutil.copytree(template,identity_hold/'template',symlinks=True)
                        write_json(identity_hold/'artifact.json',record)
                        outcome['status']='held_worker_labeled_original_identity'
                    elif hold:outcome['status']=hold
                    elif dest.exists():outcome['status']='held_existing_template_without_record'
                    else:
                        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(template,dest,symlinks=True)
                        write_json(existing,record);outcome.update(status='new_artifact_recorded',release_eligible=record['release_eligible'])
        except Exception as e:
            status='truncated_fixture_pending_evidence_review' if (
                isinstance(e,EOFError) and job['member'].startswith('evidence/')
                and job['member'].endswith('/deliberately-truncated.cpgpkg')) else 'error'
            outcome.update(status=status,error=type(e).__name__+': '+str(e))
        write_json(a.state,state)
        print(json.dumps({'status':outcome['status'],'source':job['source'],'member':job['member']}),flush=True)
    print(json.dumps({'processed':processed,'total_recorded':len(state['results'])}),flush=True)


if __name__=='__main__':main()
