#!/usr/bin/env python3
"""Network-enabled preparation only. All later phases consume locked local files."""
import hashlib,json,urllib.request,urllib.parse,datetime,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPECS=[
 {"name":"ocaml","version":"4.14.2","role":"ocaml-build-closure","url":"https://github.com/ocaml/ocaml/archive/4.14.2.tar.gz","path":"materials/ocaml-closure/ocaml-4.14.2.tar.gz","expected_algorithm":"sha256","expected_digest":"c2d706432f93ba85bd3383fa451d74543c32a4e84a1afaf3e8ace18f7f097b43","repository":"https://github.com/ocaml/ocaml.git","tag":"4.14.2","license":"LGPL-2.1-or-later WITH OCaml-LGPL-linking-exception"},
 {"name":"dune","version":"3.17.2","role":"ocaml-build-closure","url":"https://github.com/ocaml/dune/releases/download/3.17.2/dune-3.17.2.tbz","path":"materials/ocaml-closure/dune-3.17.2.tbz","expected_algorithm":"sha256","expected_digest":"9deafeed0ecfe9e65e642cd8e6197f0864f73fcd7b94b5b199ae4d2e07a2ea64","repository":"https://github.com/ocaml/dune.git","tag":"3.17.2","license":"MIT"},
 {"name":"menhir","version":"20250912","role":"tool-source","url":"https://gitlab.inria.fr/fpottier/menhir/-/archive/20250912/archive.tar.gz","path":"materials/tool-source/menhir-20250912.tar.gz","expected_algorithm":"sha512","expected_digest":"72c85ec63104d6a7c7b6305b4642b86909fcad2e46561427ad596e37e686b3c94cd382da440f058d32800a15b157b80a8242df8043440a209ba73d209657ea84","repository":"https://gitlab.inria.fr/fpottier/menhir.git","tag":"20250912","license":"GPL-2.0-only (generator); LGPL-2.0-only WITH OCaml-LGPL-linking-exception (libraries)"}]
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"CPG-worker001-offline-material-preparation/1"})
 with urllib.request.urlopen(req,timeout=90) as r:
  return r.read(),r.url
out=[]
for s in SPECS:
 p=ROOT/s["path"];p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():
  data=p.read_bytes();actual_url=s["url"]
 else:
  data,actual_url=fetch(s["url"])
 if hashlib.new(s["expected_algorithm"],data).hexdigest()!=s["expected_digest"]:
  raise RuntimeError("upstream checksum mismatch: "+s["name"])
 p.write_bytes(data)
 s.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),resolved_url=urllib.parse.urlunsplit(urllib.parse.urlsplit(actual_url)._replace(query="",fragment="")))
 ref=subprocess.run(["git","ls-remote",s["repository"],"refs/tags/"+s["tag"],"refs/tags/"+s["tag"]+"^{}"],capture_output=True,text=True,timeout=90)
 (ROOT/"evidence"/(s["name"]+"-tag-resolution.txt")).write_text(ref.stdout+ref.stderr)
 if ref.returncode==0 and ref.stdout.strip():
  lines=[l.split() for l in ref.stdout.strip().splitlines()];s["commit"]=next((l[0] for l in lines if l[1].endswith("^{}")),lines[0][0])
 else:s["commit"]=None;s["commit_unavailable_reason"]="See evidence tag-resolution log; content identity is locked by upstream checksum."
 print(s["name"],s["version"],s["bytes"],s["sha256"],flush=True)
 out.append(s)
metadata=[]
for package,version in [("ocaml-base-compiler","4.14.2"),("dune","3.17.2"),("menhir","20250912"),("menhirLib","20250912"),("menhirSdk","20250912"),("menhirCST","20250912")]:
 url=f"https://opam.ocaml.org/packages/{package}/{package}.{version}/opam"
 data,resolved=fetch(url);p=ROOT/"materials"/"opam-metadata"/(package+"."+version+".opam");p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 metadata.append({"name":package,"version":version,"url":url,"path":str(p.relative_to(ROOT)),"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
lock={"schema_version":1,"plan_id":"cpg-resource-research-20261101-v1","resource_id":"menhir","created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"sources":out,"metadata":metadata,"opam":{"required_for_this_recipe":False,"installed":False,"reason":"Exact OCaml and Dune source bootstrap; Menhir libraries built from same locked source tree. No solver or opam client is invoked."}}
(ROOT/"materials"/"sources.lock.json").write_text(json.dumps(lock,indent=2,ensure_ascii=False)+"\n")

license_manifest=[]
(ROOT/"licenses").mkdir(exist_ok=True)
for source in out:
 with tarfile.open(ROOT/source["path"]) as archive:
  members=archive.getmembers()
  if source["name"]=="menhir":
   test_members=[m.name for m in members if "/".join(m.name.split("/")[1:]).startswith("test/")]
   if test_members:
    raise RuntimeError("The source archive unexpectedly contains test/ material excluded by its root license; review before distributing")
   (ROOT/"evidence/source-scope.json").write_text(json.dumps({"archive_sha256":source["sha256"],"archive_member_count":len(members),"test_subtree_present":False,"claim":"Upstream release archive already excludes test/; original upstream bytes retained."},indent=2)+"\n")
  for member in members:
   rel="/".join(member.name.split("/")[1:])
   if member.isfile() and rel in {"LICENSE","LICENSE.md","LICENSE.QPL","COPYING","fix/LICENSE","pprint/LICENSE","coq-menhirlib/LICENSE"}:
    content=archive.extractfile(member).read();name=source["name"]+"-"+rel.replace("/","-")
    (ROOT/"licenses"/name).write_bytes(content)
    license_manifest.append({"name":source["name"],"version":source["version"],"archive_member":member.name,"local_path":"licenses/"+name,"sha256":hashlib.sha256(content).hexdigest()})
(ROOT/"licenses/manifest.json").write_text(json.dumps(license_manifest,indent=2)+"\n")
