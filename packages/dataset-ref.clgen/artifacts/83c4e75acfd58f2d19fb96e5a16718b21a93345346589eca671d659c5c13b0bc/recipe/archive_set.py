#!/usr/bin/env python3
"""Preserve and fully audit original archive bytes without resolving upstream links."""
from pathlib import Path,PurePosixPath
import hashlib,json,os,shutil,tarfile

def require(ok,message):
    if not ok: raise ValueError(message)
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def archive_members(raw):
    result=[]
    with tarfile.open(raw,'r:*') as archive:
        for member in archive:
            name=PurePosixPath(member.name)
            require(not name.is_absolute() and '..' not in name.parts,'Unsafe original archive member path')
            row={'path':member.name,'mode':member.mode,'bytes':member.size,'mtime':member.mtime}
            if member.isfile():
                with archive.extractfile(member) as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
                row.update(kind='file',sha256=checksum)
                if member.size<=1024:
                    require(not archive.extractfile(member).read().startswith(b'version https://git-lfs.github.com/spec/v1'),'Incomplete original Git LFS material')
            elif member.isdir():row['kind']='directory'
            elif member.issym():row.update(kind='symlink',target=member.linkname)
            elif member.islnk():row.update(kind='hardlink',target=member.linkname)
            else:raise ValueError('Unsupported original archive member '+member.name)
            result.append(row)
    require(len({r['path'] for r in result})==len(result),'Duplicate upstream member path')
    return result

def assemble(main_raw,source_lock,additional_locks,cache,payload):
    from compiler_playground.packages.archive import inventory
    main_raw,cache,payload=map(Path,(main_raw,cache,payload));payload.mkdir(parents=True,exist_ok=False)
    original_dir=payload/'original-archives';original_dir.mkdir()
    sources=[{'lock':source_lock,'raw':main_raw,'destination':''}]
    sources += [{'lock':r,'raw':cache/'sha256'/r['sha256'][:2]/r['sha256'],'destination':r['destination']} for r in additional_locks]
    objects={};mounts=[]
    for entry in sources:
        lock,raw=entry['lock'],entry['raw'];digest=lock['sha256']
        require(raw.is_file() and raw.stat().st_size==lock['bytes'] and sha(raw)==digest,'Original archive differs')
        if digest not in objects:
            members=archive_members(raw);name=digest+'.tar.gz';target=original_dir/name
            shutil.copyfile(raw,target);target.chmod(0o444)
            require(sha(target)==digest and target.stat().st_ino!=raw.stat().st_ino,'Original archive copy differs or shares inode')
            objects[digest]={'sha256':digest,'bytes':lock['bytes'],'path':'original-archives/'+name,'members':members}
        mounts.append({'id':lock['id'],'url':lock['url'],'sha256':digest,'bytes':lock['bytes'],'destination':entry['destination'],'git_commit':lock.get('git_commit',lock['url'].rsplit('/',1)[-1]),'strip_root':lock['strip_root']})
    descriptor={'schema_version':1,'material_representation':'complete_original_archive_set_container','source_tree_deployment':False,'archives':list(objects.values()),'original_gitlink_mounts':mounts,'policy':'All original source bytes, modes, symlinks and notices remain inside the unchanged archives. Upstream dangling links are retained and do not become resolved deployment paths.'}
    (payload/'original-archive-members.json').write_text(json.dumps(descriptor,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    rows=inventory(payload);files=[{k:v for k,v in r.items() if k!='mode'} for r in rows if r['kind']!='directory']
    return {'status':'passed','files':files,'summary':{'entries':len(files),'files':len(files),'symlinks':0,'logical_bytes':sum(r.get('bytes',0) for r in files)},'notice_and_reference_paths':[{'archive_sha256':h,'path':r['path']} for h,o in objects.items() for r in o['members'] if any(x in r['path'].lower() for x in ('license','copying','copyright','notice','readme','authors'))],'unique_original_archives':len(objects),'original_gitlink_mounts':len(additional_locks),'original_archive_members':sum(len(o['members']) for o in objects.values()),'original_regular_members':sum(sum(r['kind']=='file' for r in o['members']) for o in objects.values()),'original_link_members':sum(sum(r['kind'] in ('symlink','hardlink') for r in o['members']) for o in objects.values()),'material_representation':'complete_original_archive_set_container','source_tree_deployment':False,'upstream_programs_executed':0}
