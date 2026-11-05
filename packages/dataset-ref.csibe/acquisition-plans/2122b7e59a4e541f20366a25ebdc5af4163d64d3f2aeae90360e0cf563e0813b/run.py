#!/usr/bin/env python3
"""Acquire exact CSiBE source/gitlink materials; qualification remains separate."""
import argparse,hashlib,json,os,subprocess,tarfile
from pathlib import Path,PurePosixPath
from urllib.request import Request,urlopen

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['probe','acquire'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prefix-bytes',type=int,default=65536)
    parser.add_argument('--allow-large-recursive',action='store_true',help='Explicitly allow all recursively pinned Git submodule payloads, without a total byte cap')
    args=parser.parse_args();p=Path(__file__).resolve().parent;plan=json.loads((p/'online-plan.json').read_text());out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    result={'resource_id':'dataset-ref.csibe','status':'running','qualification':'online_acquisition_only','offline_material_qualified':False,'dataset_qualified':False,'native_execution':False,'requests':[]}
    try:
        if args.command=='probe':
            if not 1<=args.prefix_bytes<=1024*1024:raise ValueError('Prefix must be 1..1048576 bytes')
            for lock in plan['direct_submodule_gitlinks']:
                request=Request(lock['url'],headers={'User-Agent':'compiler-playground-static-online/0.21.3','Range':'bytes=0-'+str(args.prefix_bytes-1)})
                with urlopen(request,timeout=90) as response:
                    data=response.read(args.prefix_bytes);row={'url':lock['url'],'git_commit':lock['git_commit'],'resolved_url':response.geturl(),'status':response.status,'content_length':response.headers.get('Content-Length'),'content_range':response.headers.get('Content-Range'),'prefix_bytes':len(data),'prefix_sha256':hashlib.sha256(data).hexdigest(),'full_archive_verified':False};result['requests'].append(row)
            result['status']='partial_transport_observed'
        else:
            if not args.allow_large_recursive:raise ValueError('Use --allow-large-recursive to authorize the potentially large complete Git submodule acquisition')
            lock=plan['acquisition_main_lock'];raw=out/'original-main.tar.gz';copied=0
            with urlopen(Request(lock['url'],headers={'User-Agent':'compiler-playground-static-online/0.21.3'}),timeout=90) as response,raw.open('xb') as f:
                while True:
                    block=response.read(min(1024*1024,lock['bytes']-copied+1))
                    if not block:break
                    copied+=len(block)
                    if copied>lock['bytes']:raise ValueError('Original main input exceeds exact size')
                    f.write(block)
            if copied!=lock['bytes'] or sha(raw)!=lock['sha256']:raise ValueError('Original main archive identity differs')
            git=['git','-c','core.hooksPath=/dev/null','-c','protocol.file.allow=never','-c','protocol.ext.allow=never','-c','protocol.ssh.allow=never']
            env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
            checkout=out/'source';commands=[]
            def call(argv,cwd=None):
                n=len(commands);r=subprocess.run(argv,cwd=cwd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                (out/f'git-{n:03d}.stdout').write_text(r.stdout);(out/f'git-{n:03d}.stderr').write_text(r.stderr);commands.append({'argv':argv,'cwd':str(cwd) if cwd else None,'returncode':r.returncode})
                if r.returncode:raise RuntimeError('Git acquisition failed; see preserved command logs')
                return r.stdout.strip()
            call([*git,'init',str(checkout)]);call([*git,'remote','add','origin',plan['repository']],checkout)
            call([*git,'fetch','--depth=1','origin',plan['main_commit']],checkout)
            if call([*git,'rev-parse','FETCH_HEAD'],checkout)!=plan['main_commit']:raise ValueError('Git fetched a different original commit')
            call([*git,'checkout','--detach','FETCH_HEAD'],checkout)
            call([*git,'submodule','update','--init','--recursive','--depth=1'],checkout)
            substatus=call([*git,'submodule','status','--recursive'],checkout)
            if any(line.startswith(('-', '+', 'U')) for line in substatus.splitlines()):raise ValueError('A recursive gitlink is not checked out at its recorded commit')
            main_files=0
            with tarfile.open(raw) as archive:
                for member in archive:
                    parts=PurePosixPath(member.name).parts[1:]
                    if not parts or member.isdir():continue
                    if '..' in parts or PurePosixPath(member.name).is_absolute():raise ValueError('Unsafe main archive member')
                    file=checkout.joinpath(*parts)
                    if member.isfile():
                        with archive.extractfile(member) as f:expected=hashlib.file_digest(f,'sha256').hexdigest()
                        if not file.is_file() or file.is_symlink() or file.stat().st_size!=member.size or sha(file)!=expected:raise ValueError('Original main file differs: '+str(file))
                    elif member.issym():
                        if not file.is_symlink() or os.readlink(file)!=member.linkname:raise ValueError('Original main link differs')
                    else:raise ValueError('Unsupported original main member')
                    main_files+=1
            result.update(status='acquired_not_cpg_qualified',original_main_archive={'sha256':sha(raw),'bytes':raw.stat().st_size},main_members_verified=main_files,git_commands=commands,recursive_submodule_status=substatus,source=str(checkout),note='Run full CPG material packing, all-member checks, dual installation, isolation and online/offline identity qualification before granting offline material coverage.')
    except BaseException as e:
        result.update(status='failed',error_type=type(e).__name__,error=str(e))
    (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'requests':len(result['requests']),'offline_material_qualified':False}))
    return 1 if result['status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())
