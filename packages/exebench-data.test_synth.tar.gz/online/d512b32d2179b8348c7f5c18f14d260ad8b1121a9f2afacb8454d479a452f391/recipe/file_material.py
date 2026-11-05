"""Copy one fixed opaque input without extracting or rewriting its contents."""
from pathlib import Path, PurePosixPath
import hashlib, shutil
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def assemble(raw, lock, additional, cache, payload):
    from compiler_playground.packages.archive import inventory
    raw,payload=Path(raw),Path(payload)
    if lock['extract'] is not False or additional:raise ValueError('Expected one original non-extracted input')
    path=PurePosixPath(lock['material_path'])
    if path.is_absolute() or '..' in path.parts or not path.parts:raise ValueError('Unsafe declared material path')
    if raw.stat().st_size!=lock['bytes'] or sha(raw)!=lock['sha256']:raise ValueError('Original input changed')
    payload.mkdir(parents=True,exist_ok=False);target=payload/path
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(raw,target);target.chmod(0o444)
    if sha(target)!=lock['sha256'] or (target.stat().st_ino==raw.stat().st_ino and target.stat().st_dev==raw.stat().st_dev):raise ValueError('Input copy differs or shares inode')
    rows=inventory(payload);files=[r for r in rows if r['kind']=='file']
    if len(files)!=1 or files[0]['path']!=str(path):raise ValueError('Unexpected material files')
    return {'status':'passed','files':files,'summary':{'entries':len(files),'files':len(files),'symlinks':0,'logical_bytes':lock['bytes']},
            'notice_and_reference_paths':[], 'material_representation':'original_locked_file_container','source_tree_deployment':False,
            'original_extract_rule_preserved':True,'policy':'The complete declared archive is retained byte for byte at its original material path. Per-record licenses and contents remain inside it; no execution, data-interface or whole-corpus completion is inferred.'}
