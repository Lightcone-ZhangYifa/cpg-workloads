#!/usr/bin/env python3
"""Exact-archive material reconstruction; never extract upstream link targets."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import online_material_base as base


def prepare_artifact(recipe, template, directory, raw, work, output, *, discard=False):
    from compiler_playground.packages import pack, verify_package
    from compiler_playground.packages.archive import inventory
    base.require(recipe['layout']=='complete_original_archive_container_with_audited_member_index','Wrong explicit archive-container layout')
    generator=recipe['archive_generator']
    helper=directory/'archive_material.py'
    base.require(generator['delivered_path']=='archive_material.py' and helper.stat().st_size==generator['bytes'] and base.sha(helper)==generator['sha256'],'Archive inventory generator identity differs')
    module_spec=importlib.util.spec_from_file_location('fixed_archive_material_generator',helper)
    module=importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    lock=recipe['original_source_locks'][0]
    payload=work/'payload'
    archive_members=module.create(raw,payload,lock)
    base.require(archive_members['original_source_lock']==lock and archive_members['representation']=='exact-archive-with-member-inventory','Generated archive index changed original source identity')
    base.require(module.verify(payload,lock)==archive_members,'Archive-container full member verification differs')
    payload.chmod(next(r['mode'] for r in template['files'] if r['path']=='payload'))
    expected=[{**r,'path':r['path'][8:]} for r in template['files'] if r['path'].startswith('payload/')]
    observed=inventory(payload)
    base.require(observed==expected,'Exact archive/member inventory differs from qualified offline material')
    archive=work/(recipe['resource_id']+'.material.cpgpkg.tar.gz')
    recipe_dir,tools_dir=directory/'recipe',directory/'tools'
    packed=pack(template['package'],archive,method='material',payload=payload,
                recipe_dir=recipe_dir if recipe_dir.is_dir() else None,
                tools_dir=tools_dir if tools_dir.is_dir() else None,
                prefix=template['prefix_policy']['prefix'],provenance=template['provenance'],
                resolved_dependencies=template['resolved_dependencies'])
    expected_artifact=recipe['offline_artifact']
    checked=verify_package(archive,expected_sha256=expected_artifact['sha256'],expected_bytes=expected_artifact['bytes'])
    base.require(checked['manifest']==template,'Archive-container offline manifest differs')
    target=None
    if not discard:
        target=output/archive.name
        base.require(not target.exists(),'Offline output already exists')
        shutil.copyfile(archive,target)
        base.require(base.sha(target)==expected_artifact['sha256'] and target.stat().st_ino!=archive.stat().st_ino,'Independent artifact copy differs')
    return {'status':'passed','method':'material','sha256':packed['sha256'],'bytes':packed['bytes'],
            'path':str(target) if target else None,'byte_identical_to_existing_offline_artifact':True,
            'manifest_sha256':template['manifest_sha256'],'payload_files':sum(r['kind']=='file' for r in observed),
            'payload_symlinks':sum(r['kind']=='symlink' for r in observed),'payload_logical_bytes':sum(r.get('bytes',0) for r in observed),
            'temporary_reproduction_discarded_after_inventory':discard,'qualification_stage':'complete_offline_artifact_reproduction',
            'installation_or_execution_performed':False,'material_representation':'exact-archive-with-member-inventory',
            'original_archive_members':len(archive_members['members']),
            'original_archive_regular_files':sum(r['kind']=='file' for r in archive_members['members']),
            'original_archive_links':sum(r['kind'] in ('symlink','hardlink') for r in archive_members['members']),
            'original_archive_bytes_preserved':True,'upstream_links_extracted':False}


if __name__=='__main__':
    base.prepare_artifact=prepare_artifact
    raise SystemExit(base.main())
