#!/usr/bin/env python3
import argparse,hashlib,json,pathlib,tarfile
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--material-path',required=True)
p.add_argument('--sha',required=True);p.add_argument('--bytes',type=int,required=True)
p.add_argument('--files',required=True);p.add_argument('--count',type=int,required=True);args=p.parse_args()
material=pathlib.Path(args.prefix)/args.material_path
paths=json.loads(args.files)
if material.is_file():
 h=hashlib.sha256(material.read_bytes()).hexdigest()
 assert material.stat().st_size==args.bytes and h==args.sha
 with tarfile.open(material,'r:gz') as arc:
  members=arc.getmembers()
  assert len(members)==args.count
  assert not any(m.isdev() or m.issym() or m.islnk() for m in members)
else:
 assert material.is_dir()
 for rel in paths: assert (material/rel).is_file(), rel
 assert sum(1 for x in material.rglob('*') if x.is_file())>0
print(json.dumps({'status':'passed','scope':'full packaged static material availability, not native build',
  'material_path':str(material),'source_sha256':args.sha,'static_witnesses':len(paths)},sort_keys=True))
