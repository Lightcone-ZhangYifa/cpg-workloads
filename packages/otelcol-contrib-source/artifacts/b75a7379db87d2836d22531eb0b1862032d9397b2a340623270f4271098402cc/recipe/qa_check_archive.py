#!/usr/bin/env python3
"""Offline complete-source TAR validation, no Go module download or build claims."""
import argparse, hashlib, json, pathlib, tarfile
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);args=p.parse_args()
target=pathlib.Path(args.prefix)/'sources/otelcol-contrib-0.163.0.tar.gz'
blob_sha=hashlib.sha256(target.read_bytes()).hexdigest()
expected='a9277bf9d19f9359a4a6f262e9c6cd98524bd6f2442950a8dce615fbe062f98e'
assert blob_sha==expected
assert target.stat().st_size==16944016
with tarfile.open(target,'r:gz') as archive:
 members=archive.getmembers()
 assert len(members)==16969
 root='opentelemetry-collector-contrib-0.163.0/'
 assert all(m.name==root[:-1] or m.name.startswith(root) for m in members)
 assert not any(m.name.startswith('/') or '..' in pathlib.PurePosixPath(m.name).parts or m.isdev() for m in members)
 assert sum(x.isfile() for x in members)==13916
 assert all(not x.issym() and not x.islnk() for x in members)
 names={m.name for m in members}
 assert root+'LICENSE' in names and root+'README.md' in names
 assert root+'Makefile' in names
 gomods=[m.name for m in members if m.name.endswith('/go.mod')]
 assert len(gomods)==351
 logical=sum(m.size for m in members if m.isfile())
 assert logical==90310786
 result={'status':'passed','scope':'complete pinned root source archive only, external Go modules unverified',
         'sha256':blob_sha,'size_bytes':target.stat().st_size,'tar_members':len(members),
         'regular_files':13916,'logical_regular_bytes':logical,'go_mod_files':len(gomods),
         'external_module_closure':'not_proven','go_native_build':'not_run','original_target_execution':'not_run'}
 print(json.dumps(result,sort_keys=True))
