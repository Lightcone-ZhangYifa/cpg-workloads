#!/usr/bin/env python3
"""Bounded original-archive acquisition for oversized immutable source resources."""
from pathlib import Path,PurePosixPath
from urllib.request import Request,urlopen
import argparse,hashlib,io,json,tarfile,zlib,os

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)
def header_probe(data,commit):
 decoded=zlib.decompressobj(31).decompress(data,2*1024*1024)
 with tarfile.open(fileobj=io.BytesIO(decoded),mode='r:') as archive:
  member=archive.next();require(member is not None,'Missing TAR header');root=PurePosixPath(member.name).parts[0];require(root.endswith('-'+commit),'Observed archive root differs from original commit')
  return {'original_archive_root':root,'first_header_path':member.name,'prefix_tar_header_observed':True,'full_archive_verified':False}
def inspect_archive(path,commit,max_expanded):
 rows=[];expanded=0
 with tarfile.open(path,'r:*') as archive:
  for member in archive:
   q=PurePosixPath(member.name);require(q.parts and not q.is_absolute() and '..' not in q.parts and q.parts[0].endswith('-'+commit),'Original archive path or commit root differs')
   row={'path':member.name,'mode':member.mode,'bytes':member.size}
   if member.isfile():
    expanded+=member.size;require(expanded<=max_expanded,'Expanded archive exceeds explicit limit')
    with archive.extractfile(member) as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    row.update(kind='file',sha256=digest)
   elif member.isdir():row['kind']='directory'
   elif member.issym():row.update(kind='symlink',target=member.linkname)
   elif member.islnk():row.update(kind='hardlink',target=member.linkname)
   else:raise ValueError('Unexpected original archive member kind')
   rows.append(row)
 return rows,expanded

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['probe','acquire']);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--prefix-bytes',type=int,default=262144);parser.add_argument('--max-bytes',type=int,default=128*1024*1024);parser.add_argument('--max-expanded-bytes',type=int,default=10*1024*1024*1024);args=parser.parse_args()
 directory=Path(__file__).resolve().parent;plan=json.loads((directory/'online-plan.json').read_text());source=plan['original_source_locks'][0];out=args.output.resolve();require(not out.is_relative_to(directory),'Outputs must be outside the immutable recipe');out.mkdir(parents=True,exist_ok=False)
 result={'resource_id':plan['resource_id'],'status':'running','original_source':source,'command':args.command,'full_input_verified':False,'offline_material_qualified':False,'dataset_content_complete':False,'native_execution':False,'dataset_api_qualified':False,'official_benchmark_qualified':False};partial=None
 try:
  headers={'User-Agent':'compiler-playground-bounded-online-material/0.21.3'}
  if args.command=='probe':
   require(1<=args.prefix_bytes<=1024*1024,'Prefix budget must be 1..1048576 bytes');headers['Range']='bytes=0-'+str(args.prefix_bytes-1)
   with urlopen(Request(source['url'],headers=headers),timeout=90) as response:
    data=response.read(args.prefix_bytes);result['http']={'url':source['url'],'resolved_url':response.geturl(),'status':response.status,'content_length':response.headers.get('Content-Length'),'content_range':response.headers.get('Content-Range')}
   result.update(status='partial_transport_and_tar_header_observed',prefix_bytes=len(data),prefix_sha256=hashlib.sha256(data).hexdigest(),prefix_body_retained=False,**header_probe(data,plan['original_commit']))
  else:
   require(args.max_bytes>0 and args.max_expanded_bytes>0,'Acquisition budgets must be positive');partial=out/'original-download.partial';size=0;digest=hashlib.sha256()
   with urlopen(Request(source['url'],headers=headers),timeout=90) as response,partial.open('xb') as f:
    result['http']={'url':source['url'],'resolved_url':response.geturl(),'status':response.status,'content_length':response.headers.get('Content-Length')}
    while True:
     block=response.read(min(1024*1024,args.max_bytes-size+1))
     if not block:break
     size+=len(block);require(size<=args.max_bytes,'Original archive exceeds explicit input budget');f.write(block);digest.update(block)
   checksum=digest.hexdigest();require(source['sha256'] is None or source['sha256']==checksum,'Original fixed SHA differs');require(source['bytes'] is None or source['bytes']==size,'Original fixed size differs');members,expanded=inspect_archive(partial,plan['original_commit'],args.max_expanded_bytes)
   final=out/(checksum+'.tar.gz');partial.rename(final);partial=None;final.chmod(0o444)
   (out/'original-archive-members.json').write_text(json.dumps(members,sort_keys=True,indent=2)+'\n')
   result.update(status='complete_original_input_acquired_not_cpg_qualified',full_input_verified=True,resolved_acquisition_lock={**source,'sha256':checksum,'bytes':size},raw_archive=str(final),original_member_count=len(members),original_expanded_regular_bytes=expanded,canonical_source_fields_modified=False)
 except BaseException as e:
  result.update(status='failed',error_type=type(e).__name__,error=str(e))
  if partial and partial.exists():
   result['discarded_partial_download']={'bytes':partial.stat().st_size,'sha256':sha(partial)};partial.unlink()
 (out/'receipt.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps({'resource':plan['resource_id'],'status':result['status'],'full_input_verified':result['full_input_verified']}));return int(result['status']=='failed')
if __name__=='__main__':raise SystemExit(main())
