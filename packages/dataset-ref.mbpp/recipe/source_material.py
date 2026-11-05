"""Explicit offline acquisition of the exact MBPP subtree from verified bytes.

Use --source-root for an exact original four-file tree, or --blob-root for a
sha256/<two-hex>/<sha256> raw input store. This helper only copies verified
bytes and never downloads or executes programs.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,stat
from compiler_playground.datasets.coding_tasks import coding_task_spec
from compiler_playground.datasets.reviewed_sources import _verified_materials

def acquire_mbpp(output, *, source_root=None, blob_root=None):
    if (source_root is None) == (blob_root is None):
        raise ValueError('Select exactly one explicit source tree or raw blob store')
    spec=coding_task_spec('mbpp');out=Path(output).absolute()
    if out.exists() or out.is_symlink():raise FileExistsError(out)
    source=Path(source_root).resolve(strict=True) if source_root is not None else None
    if source is not None:
        _verified_materials(source,spec)
        if out.resolve().is_relative_to(source):raise ValueError('Output must be outside the original MBPP tree')
    out.mkdir(parents=True);destination=out/'source';destination.mkdir();rows=[]
    for expected in spec['source_materials']['files']:
        path=source/expected['path'] if source is not None else Path(blob_root)/'sha256'/expected['sha256'][:2]/expected['sha256']
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise ValueError('Expected an ordinary verified original MBPP file')
        data=path.read_bytes()
        if (len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']
                or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=expected['git_blob_sha1']):
            raise ValueError('Original MBPP blob identity differs')
        target=destination/expected['path'];target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(data)
        target.chmod(expected['mode']);after=target.stat()
        if after.st_nlink!=1 or (st.st_dev,st.st_ino)==(after.st_dev,after.st_ino):raise ValueError('MBPP acquisition reused an inode')
        if target.read_bytes()!=data:raise ValueError('MBPP ordinary copy changed bytes')
        rows.append({**expected,'source_inode':st.st_ino,'copy_inode':after.st_ino})
    _verified_materials(destination,spec)
    report={'format':'cpg-mbpp-offline-acquisition-v1','status':'passed','revision':spec['revision'],'source_materials':spec['source_materials'],'source_root':str(destination),'files':rows,'network_used':False,'programs_executed':False,'qualification':'source_material_identity_only'}
    (out/'acquisition.json').write_text(json.dumps(report,indent=2)+'\n')
    return destination,report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--source-root',type=Path);group.add_argument('--blob-root',type=Path);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args();_,result=acquire_mbpp(a.output,source_root=a.source_root,blob_root=a.blob_root);print(json.dumps(result,indent=2))
