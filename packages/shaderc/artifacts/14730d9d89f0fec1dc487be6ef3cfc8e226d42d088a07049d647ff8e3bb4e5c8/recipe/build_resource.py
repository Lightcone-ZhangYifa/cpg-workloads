#!/usr/bin/env python3
"""Offline builds from the original, locked CPG source assets; no acquisition."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def run(argv, cwd=None):
    print('+', ' '.join(map(str, argv)), flush=True)
    subprocess.run(list(map(str, argv)), cwd=cwd, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('name', choices=['glslang', 'shaderc', 'spirv-headers'])
    for arg in ['assets', 'build', 'prefix']:
        p.add_argument('--' + arg, type=Path, required=True)
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args()
    assets, build, prefix = a.assets.resolve(), a.build.resolve(), a.prefix.resolve()
    if a.jobs < 1:
        raise ValueError('jobs must be positive')
    if len({assets, build, prefix}) != 3:
        raise ValueError('source assets, build and installation must be independent')
    build.mkdir(parents=True, exist_ok=True)
    (build/'tmp').mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(build/'tmp')
    prefix.mkdir(parents=True, exist_ok=True)
    src = assets / a.name
    license_dir = prefix / 'share' / 'licenses' / a.name
    license_dir.mkdir(parents=True, exist_ok=True)
    if a.name == 'spirv-headers':
        gen = src / 'tools/buildHeaders'
        (prefix / 'bin').mkdir(exist_ok=True)
        run(['g++', '-O2', '-std=c++11', str(gen/'main.cpp'), str(gen/'header.cpp'),
             str(gen/'jsonToSpirv.cpp'), str(gen/'jsoncpp/dist/jsoncpp.cpp'),
             '-o', str(prefix/'bin/buildSpvHeaders')])
        shutil.copytree(src, prefix/'share/spirv-headers', dirs_exist_ok=True)
        shutil.copytree(src/'include', prefix/'include', dirs_exist_ok=True)
    else:
        cmake = os.environ.get('CPG_CMAKE', 'cmake')
        optimization = '-O1' if a.name == 'shaderc' else '-O2'
        cfg = [cmake, '-S', str(src), '-B', str(build/'cmake'),
               '-G', 'Unix Makefiles', '-DCMAKE_BUILD_TYPE=Release',
               '-DCMAKE_C_FLAGS_RELEASE='+optimization+' -DNDEBUG -pipe',
               '-DCMAKE_CXX_FLAGS_RELEASE='+optimization+' -DNDEBUG -pipe',
               '-DENABLE_PCH=OFF',
               '-DCMAKE_INSTALL_PREFIX='+str(prefix)]
        if a.name == 'glslang':
            cfg += ['-DENABLE_OPT=OFF', '-DGLSLANG_TESTS=OFF', '-DENABLE_SPVREMAPPER=OFF',
                    '-DBUILD_EXTERNAL=OFF', '-DGLSLANG_ENABLE_INSTALL=ON']
            run(cfg)
            run([cmake, '--build', str(build/'cmake'), '-j', str(a.jobs)])
            run([cmake, '--install', str(build/'cmake')])
            exe = prefix/'bin/glslang'
            if exe.exists() and not (prefix/'bin/glslangValidator').exists():
                (prefix/'bin/glslangValidator').symlink_to('glslang')
        else:
            cfg += ['-DSHADERC_SKIP_TESTS=ON', '-DSHADERC_SKIP_EXAMPLES=ON',
                    '-DSHADERC_SKIP_COPYRIGHT_CHECK=ON', '-DSHADERC_ENABLE_WERROR_COMPILE=OFF',
                    '-DSHADERC_GLSLANG_DIR='+str(assets/'glslang'),
                    '-DSHADERC_SPIRV_TOOLS_DIR='+str(assets/'spirv-tools'),
                    '-DSHADERC_SPIRV_HEADERS_DIR='+str(assets/'spirv-headers')]
            run(cfg)
            run([cmake, '--build', str(build/'cmake'), '-j', str(a.jobs),
                 '--target', 'glslc_exe', 'shaderc_shared', 'shaderc_combined'])
            (prefix/'bin').mkdir(exist_ok=True)
            (prefix/'lib').mkdir(exist_ok=True)
            shutil.copy2(build/'cmake/glslc/glslc', prefix/'bin/glslc')
            for f in ['libshaderc_shared.so.1', 'libshaderc_combined.a']:
                shutil.copy2(build/'cmake/libshaderc'/f, prefix/'lib'/f)
            (prefix/'lib/libshaderc_shared.so').symlink_to('libshaderc_shared.so.1')
            shutil.copytree(src/'libshaderc/include', prefix/'include', dirs_exist_ok=True)
            for dep in ['glslang', 'spirv-tools', 'spirv-headers']:
                dest = license_dir/dep
                dest.mkdir(exist_ok=True)
                for f in (assets/dep).glob('*'):
                    if f.is_file() and f.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                        shutil.copy2(f, dest/f.name)
    for f in src.glob('*'):
        if f.is_file() and f.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
            shutil.copy2(f, license_dir/f.name)
    print('OFFLINE_BUILD_OK', a.name, flush=True)


if __name__ == '__main__':
    main()
