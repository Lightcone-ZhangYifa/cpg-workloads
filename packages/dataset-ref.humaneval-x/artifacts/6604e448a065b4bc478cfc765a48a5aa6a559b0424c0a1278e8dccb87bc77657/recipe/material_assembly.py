#!/usr/bin/env python3
"""Assemble complete immutable upstream main archive plus exact gitlink archives.

This helper neither changes upstream bytes nor grants native build qualification.
It requires a fully locked, previously reviewed archive for every original Git
submodule and retains original files, modes and safe symbolic links.
"""
from pathlib import Path, PurePosixPath
import hashlib, json, os, tarfile


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def retained_members(raw, payload, prefix=''):
    result = []
    with tarfile.open(raw) as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts[1:]
            if not parts or member.isdir(): continue
            local = PurePosixPath(*parts).as_posix()
            path = payload / local
            relative = (PurePosixPath(prefix) / local).as_posix()
            if member.isfile():
                with archive.extractfile(member) as f: digest=hashlib.file_digest(f, 'sha256').hexdigest()
                require(path.is_file() and not path.is_symlink() and path.stat().st_size == member.size and sha(path)==digest,
                        'Original file changed: '+relative)
                if member.size <= 1024:
                    require(not path.read_bytes().startswith(b'version https://git-lfs.github.com/spec/v1'),
                            'Unfetched LFS object: '+relative)
                result.append({'path':relative,'kind':'file','bytes':member.size,'sha256':digest})
            elif member.issym():
                require(path.is_symlink() and os.readlink(path)==member.linkname, 'Original link changed: '+relative)
                result.append({'path':relative,'kind':'symlink','target':member.linkname})
            else: raise ValueError('Unreviewed upstream member: '+relative)
    return result


def assemble(main_raw, source_lock, additional_locks, cache, payload):
    from compiler_playground.resource_deploy import unpack_archive
    from compiler_playground.packages.archive import inventory
    main_raw, cache, payload=map(Path,(main_raw,cache,payload))
    require(sha(main_raw)==source_lock['sha256'] and main_raw.stat().st_size==source_lock['bytes'], 'Original main archive differs')
    unpack_archive(main_raw,payload,strip_root=source_lock['strip_root'])
    expected=retained_members(main_raw,payload)
    bindings=[];destinations=set()
    for lock in sorted(additional_locks,key=lambda r:(len(PurePosixPath(r['destination']).parts),r['destination'])):
        rel=PurePosixPath(lock['destination'])
        require(rel.as_posix()==lock['destination'] and not rel.is_absolute() and '..' not in rel.parts and rel.as_posix() not in destinations,
                'Unsafe or duplicate submodule mount')
        destinations.add(rel.as_posix());target=payload / rel
        require(not target.is_symlink() and target.parent.resolve().is_relative_to(payload.resolve()),'Unsafe mount parent')
        if target.exists():
            require(target.is_dir() and not any(target.iterdir()),'Submodule would overwrite original material')
            target.rmdir()
        raw=cache/'sha256'/lock['sha256'][:2]/lock['sha256']
        require(raw.is_file() and raw.stat().st_size==lock['bytes'] and sha(raw)==lock['sha256'],'Exact supplemental archive missing')
        unpack_archive(raw,target,strip_root=True)
        rows=retained_members(raw,target,rel.as_posix());expected.extend(rows)
        bindings.append({'destination':rel.as_posix(),'sha256':lock['sha256'],'bytes':lock['bytes'],'members':len(rows)})
    expected_by_path={r['path']:r for r in expected};require(len(expected_by_path)==len(expected),'Upstream archives overlap')
    observed=inventory(payload)  # Strict resolution of every symlink, after all exact mounts.
    actual={r['path']:{k:v for k,v in r.items() if k!='mode'} for r in observed if r['kind']!='directory'}
    require(actual==expected_by_path,'Assembled material differs from exact full upstream closure')
    notices=[r['path'] for r in expected if any(t in r['path'].lower() for t in ('license','copying','copyright','notice','readme','authors'))]
    return {'status':'passed','files':expected,'summary':{'entries':len(expected),'files':sum(r['kind']=='file' for r in expected),'symlinks':sum(r['kind']=='symlink' for r in expected),'logical_bytes':sum(r.get('bytes',0) for r in expected)},'notice_and_reference_paths':notices,'additional_archives':bindings,'all_original_gitlinks_filled':True,'source_tree_scope':'complete_main_archive_and_recursive_exact_gitlink_archives','native_compilation_or_external_runtime_dependency_qualification':False}
