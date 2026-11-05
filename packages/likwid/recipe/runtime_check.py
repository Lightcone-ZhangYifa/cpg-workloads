#!/usr/bin/env python3
"""Verify private Perl closure, retained inputs and relocated library paths."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',type=Path,required=True);a=p.parse_args();root=a.prefix.resolve()
    profile=json.loads((root/'share/compiler-playground/likwid/profile.json').read_text())
    for row in profile['recipe_inputs']:
        f=root/'share/likwid/inputs'/Path(row['filename']).name
        assert f.stat().st_size==row['bytes'] and sha(f)==row['sha256']
    args=[str(root/'libexec/cpg-perl'),'-MConfig','-MTime::HiRes','-Mthreads','-MThread::Queue','-MGetopt::Long','-MJSON::PP','-e','print JSON::PP->new->canonical->encode({version=>"$^V",modules=>\\%INC}),"\\n"']
    r=subprocess.run(args,capture_output=True,text=True,check=True,timeout=20);v=json.loads(r.stdout)
    assert v['version']=='v5.38.2' and all(Path(x).resolve().is_relative_to(root) for x in v['modules'].values())
    for name in ('likwid-accessD','likwid-setFreq'):
        assert (root/'sbin'/name).is_file() and (root/'libexec/native'/name).is_file()
        assert not ((root/'sbin'/name).stat().st_mode & 0o6000)
    print(json.dumps({'status':'passed','private_perl_version':v['version'],'private_modules':len(v['modules']),'retained_debs':len(profile['recipe_inputs']),'daemon_started':False,'counter_collection_qualified':False}))

if __name__=='__main__':main()
