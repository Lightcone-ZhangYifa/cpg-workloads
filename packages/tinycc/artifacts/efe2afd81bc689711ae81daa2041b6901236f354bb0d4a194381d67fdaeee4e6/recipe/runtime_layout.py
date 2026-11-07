"""Create relocation-safe entrypoints and detach upstream local symlinks."""
import json, pathlib, shutil, re

def prepare_prefix(prefix,name,worker_root):
    prefix=pathlib.Path(prefix)
    for p in list(prefix.rglob('*')):
        if p.is_symlink():
            target=p.resolve()
            target.relative_to(prefix.resolve())
            if not target.is_file():raise ValueError('Only internal file symlinks can be copied: '+str(p))
            data=target.read_bytes(); mode=target.stat().st_mode&0o777
            p.unlink();p.write_bytes(data);p.chmod(mode)
    libexec=prefix/'libexec';libexec.mkdir(exist_ok=True)
    if name=='tinycc':
        shutil.move(str(prefix/'bin/tcc'),str(libexec/'tcc.bin'))
        wrapper='#!/bin/sh\nset -eu\nprefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexec "$prefix/libexec/tcc.bin" -B"$prefix/lib/tcc" "$@"\n'
        (prefix/'bin/tcc').write_text(wrapper);(prefix/'bin/tcc').chmod(0o755)
    elif name=='luajit':
        shutil.move(str(prefix/'bin/luajit'),str(libexec/'luajit.bin'))
        module_dir=next((prefix/'share').glob('luajit-2.1*')).name
        wrapper='#!/bin/sh\nset -eu\nprefix=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexport LUA_PATH="$prefix/share/'+module_dir+'/?.lua;${LUA_PATH:-;;}"\nexport LUA_CPATH="$prefix/lib/lua/5.1/?.so;${LUA_CPATH:-;;}"\nexec "$prefix/libexec/luajit.bin" "$@"\n'
        (prefix/'bin/luajit').write_text(wrapper);(prefix/'bin/luajit').chmod(0o755)
    if name=='luajit':
        frozen=prefix/'share/luajit/frozen-apt';frozen.mkdir(parents=True,exist_ok=True)
        shutil.copy2(worker_root/'raw/libluajit-frozen-dev.deb',frozen/'libluajit-frozen-dev.deb')
        meta_file={'resource_id':'apt.libluajit-5.1-dev','archive_sha256':'ef46b0ec8984a6cc00120e156d5670a3f2aff448ec31dc17222c14f0a2248aaf','embedding_probe':'bin/cpg-frozen-luajit-check statically links the original archive member; the regular lib/ tree is separately source-built','system_package_installed':False}
        (frozen/'identity.json').write_text(json.dumps(meta_file,indent=2)+'\n')
    for pc in (prefix/'lib/pkgconfig').glob('*.pc'):
        text=pc.read_text();text=re.sub(r'^prefix=.*$',r'prefix=${pcfiledir}/../..',text,flags=re.MULTILINE);pc.write_text(text)
    for la in (prefix/'lib').glob('*.la'):
        saved=prefix/'share'/name/'build-metadata';saved.mkdir(parents=True,exist_ok=True)
        shutil.move(str(la),str(saved/la.name))
    meta={'schema_version':1,'name':name,'execution_scope':'Linux x86_64 SysV, measured with Ubuntu 24.04 userspace and GCC 13.3.0','source_built':True,'network_required_for_install_or_profile':False,'full_upstream_regression_suite':False,'runtime_profile':'python3 run_checks.py'}
    lock=json.loads((worker_root/'inputs.lock.json').read_text())
    meta['input_locks']=[i for i in lock['inputs'] if i['name'] in ([name,'libluajit-frozen-dev'] if name=='luajit' else [name])]
    (prefix/'cpg-resource.json').write_text(json.dumps(meta,indent=2)+'\n')
    shutil.copy2(worker_root/'fixtures/run_checks.py',prefix/'run_checks.py')
