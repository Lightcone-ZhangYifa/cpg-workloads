"""Verified CPG helper: inventory first, then invoke the installed functional check."""
import hashlib,json,os,pathlib,stat,subprocess,sys

def inventory(root):
    root=pathlib.Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Prefix must be an ordinary directory')
    root=root.resolve(strict=True);rows=[]
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in sorted([*dirs,*files]):
            path=pathlib.Path(directory)/name;rel=path.relative_to(root).as_posix()
            if rel=='.cpg-prefix.json':continue
            s=path.lstat();row={'path':rel,'mode':stat.S_IMODE(s.st_mode)&0o777}
            if stat.S_ISREG(s.st_mode):
                h=hashlib.sha256()
                with path.open('rb') as f:
                    for b in iter(lambda:f.read(1048576),b''):h.update(b)
                row.update(kind='file',bytes=s.st_size,sha256=h.hexdigest())
            elif stat.S_ISDIR(s.st_mode):row.update(kind='directory')
            elif stat.S_ISLNK(s.st_mode):
                if not path.resolve(strict=True).is_relative_to(root):raise ValueError('Symlink escapes prefix')
                row.update(kind='symlink',target=os.readlink(path))
            else:raise ValueError('Unsupported installed file type')
            rows.append(row)
        dirs[:]=sorted(d for d in dirs if not (pathlib.Path(directory)/d).is_symlink())
    return sorted(rows,key=lambda x:x['path'])

def main():
    here=pathlib.Path(__file__).resolve().parent;prefix=pathlib.Path(sys.argv[1]);build=pathlib.Path(sys.argv[2])
    try:
        expected=json.loads((here/'payload-inventory.json').read_text());actual=inventory(prefix)
        if actual!=expected:raise ValueError('Installed payload differs from the frozen package inventory')
    except (ValueError,OSError) as e:
        print(json.dumps({'status':'refused','error':'CPG_PREFIX_INTEGRITY_MISMATCH','reason':str(e)}));return 86
    argv=json.loads((here/'check-command.json').read_text())
    argv=[x.replace('{prefix}',str(prefix)).replace('{build}',str(build)) for x in argv]
    result=subprocess.run(argv,cwd=build)
    return result.returncode
if __name__=='__main__':sys.exit(main())
