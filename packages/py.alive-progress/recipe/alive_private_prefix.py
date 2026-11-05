"""Install the exact alive-progress wheel without overwriting about-time's LICENSE.

The original pip installer and wheel bytes are retained. Only this distribution
uses a private prefix inside its selected virtual environment. A non-executable
relative .pth entry makes that prefix visible to the same interpreter. This is
a resource-specific layout, not a generic alternate package manager.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import sysconfig
from urllib.parse import unquote, urlsplit

NAME = 'alive-progress'
VERSION = '3.3.0'
SOURCE_SHA256 = '63dd33bb94cde15ad9e5b666dbba8fedf71b72a4935d6fb9a92931e69402c9ff'
SOURCE_BYTES = 78403
LAYOUT_NAME = 'alive-progress-3.3.0'
PTH_NAME = 'cpg_alive_progress_3_3_0.pth'
WHEEL_LOCK_SHA256 = 'c4e44dfb4ef19224e98694d023abfbb5754d42b24ec9741b215c17fc99d75bc5'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary_path(path, root, *, directory=False, missing=False):
    path, root = Path(path).absolute(), Path(root).absolute()
    require(path == root or root in path.parents, 'Managed layout path escaped its environment')
    for current in [path, *path.parents]:
        require(not current.is_symlink(), 'Managed layout path traverses a symbolic link')
        if current == root:
            break
    if missing and not path.exists():
        return path
    require(path.is_dir() if directory else path.is_file(), 'Missing ordinary managed layout object')
    if not directory:
        require(path.stat().st_nlink == 1, 'Managed layout file is shared by hard link')
    return path


def paths(prefix):
    prefix = Path(prefix).absolute()
    require(prefix == Path(sys.prefix).absolute() and sys.prefix != sys.base_prefix,
            'Use the selected isolated virtual-environment interpreter')
    ordinary_path(prefix, prefix, directory=True)
    private = prefix / '.cpg-wheel-layouts' / LAYOUT_NAME
    purelib = Path(sysconfig.get_path('purelib')).absolute()
    private_lib = Path(sysconfig.get_path('purelib', vars={'base': str(private), 'platbase': str(private)})).absolute()
    ordinary_path(purelib, prefix, directory=True)
    ordinary_path(private, prefix, directory=True, missing=True)
    require(private_lib.is_relative_to(private), 'Interpreter installation scheme escaped the private prefix')
    pth = purelib / PTH_NAME
    pointer = os.path.relpath(private_lib, purelib) + '\n'
    require(not pointer.startswith(('import ', 'import\t')) and '\n' not in pointer[:-1], 'Unsafe .pth pointer')
    return prefix, private, purelib, private_lib, pth, pointer


def inspect_distribution(private, private_lib):
    ordinary_path(private_lib, private, directory=True)
    found = list(importlib.metadata.distributions(path=[str(private_lib)]))
    require(len(found) == 1, 'Private prefix contains an unexpected distribution set')
    dist = found[0]
    require(dist.metadata['Name'].lower().replace('_', '-') == NAME and dist.version == VERSION,
            'Private distribution identity differs from the fixed wheel')
    info = Path(dist._path).absolute()
    ordinary_path(info, private, directory=True)
    require(info.parent == private_lib and info.name == 'alive_progress-3.3.0.dist-info', 'Unexpected metadata location')
    record = ordinary_path(info / 'RECORD', private)
    rows = list(csv.reader(io.StringIO(record.read_text())))
    require(rows and len({row[0] for row in rows}) == len(rows), 'Missing or duplicate installed RECORD rows')
    lock_path = Path(__file__).with_name('alive-wheel-files.json')
    require(lock_path.is_file() and not lock_path.is_symlink() and digest(lock_path) == WHEEL_LOCK_SHA256,
            'Original wheel member lock changed')
    lock = json.loads(lock_path.read_text())
    require(lock['source_sha256'] == SOURCE_SHA256 and lock['source_bytes'] == SOURCE_BYTES
            and lock['source_members'] == len(lock['wheel_members']) == 36,
            'Wrong original wheel member contract')
    original = {}
    record_name = 'alive_progress-3.3.0.dist-info/RECORD'
    for item in lock['wheel_members']:
        name = item['wheel_path']
        if name == record_name:
            continue
        if name == 'alive_progress-3.3.0.data/data/LICENSE':
            target = private / 'LICENSE'
            relative = os.path.relpath(target, private_lib)
        else:
            require('.data/' not in name, 'Unreviewed wheel installation scheme')
            target = private_lib / name
            relative = name
        require(relative not in original, 'Original wheel members collide after installation')
        original[relative] = dict(item, target=target)
    generated = {name: private_lib / name for name in lock['installation_scheme']['pip_generated_only']}
    require(len(generated) == 3 and not set(generated) & set(original), 'Wrong pip-generated member set')
    expected_names = set(original) | set(generated) | {record_name}
    require({row[0] for row in rows} == expected_names,
            'Installed RECORD changes the exact original-wheel ownership set')
    hashed = []
    for row in rows:
        require(len(row) == 3 and row[0] and '\\' not in row[0], 'Malformed installed RECORD')
        target = Path(dist.locate_file(row[0])).absolute()
        resolved = target.resolve()
        require(resolved.is_relative_to(private), 'Installed RECORD escapes its owned private prefix')
        ordinary_path(target, private)
        ordinary_path(resolved, private)
        expected_target = original[row[0]]['target'] if row[0] in original else generated.get(row[0], record)
        require(resolved == expected_target.resolve(), 'Installed RECORD redirects an owned member')
        if row[0] in original:
            bound = original[row[0]]
            require(digest(resolved) == bound['sha256'] and resolved.stat().st_size == bound['bytes'],
                    'Installed member no longer matches the fixed original wheel: ' + row[0])
        elif row[0].endswith('/INSTALLER'):
            require(resolved.read_bytes() == b'pip\n', 'Unexpected installer metadata')
        elif row[0].endswith('/REQUESTED'):
            require(resolved.read_bytes() == b'', 'Unexpected requested metadata')
        elif row[0].endswith('/direct_url.json'):
            direct = json.loads(resolved.read_text())
            require(set(direct) == {'url', 'archive_info'}, 'Unexpected direct URL metadata fields')
            parsed = urlsplit(direct['url'])
            require(parsed.scheme == 'file' and not parsed.netloc and not parsed.query and not parsed.fragment,
                    'Original wheel direct URL is not a plain local file')
            require(Path(unquote(parsed.path)).name == 'alive_progress-3.3.0-py3-none-any.whl',
                    'Direct URL names a different original wheel')
            require(direct['archive_info'] == {'hash': 'sha256=' + SOURCE_SHA256, 'hashes': {'sha256': SOURCE_SHA256}},
                    'Direct URL does not bind the original wheel hash')
        if row[1]:
            require(row[0] != record_name, 'Installed RECORD must not hash itself')
            algorithm, separator, encoded = row[1].partition('=')
            require(separator and algorithm == 'sha256', 'Unsupported installed RECORD hash')
            actual = base64.urlsafe_b64encode(bytes.fromhex(digest(resolved))).decode().rstrip('=')
            require(actual == encoded, 'Installed RECORD content differs: ' + row[0])
            require(row[2].isdigit() and int(row[2]) == resolved.stat().st_size,
                    'Installed RECORD size differs: ' + row[0])
            hashed.append({'path': resolved.relative_to(private).as_posix(), 'sha256': digest(resolved),
                           'bytes': resolved.stat().st_size})
        else:
            require(row[0] == record_name and row[2] == '', 'Unhashed ordinary installed content is not permitted')
    require(any(row['path'] == 'LICENSE' for row in hashed), 'The original wheel LICENSE is not retained')
    return {'distribution': NAME, 'version': VERSION, 'hashed_files': hashed,
            'record_sha256': digest(record), 'metadata_sha256': digest(info / 'METADATA')}


def pip(arguments):
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PIP_PREFIX', 'PIP_TARGET', 'PIP_USER'):
        env.pop(name, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PIP_CONFIG_FILE=os.devnull)
    subprocess.run([sys.executable, '-I', '-m', 'pip', '--isolated', *arguments], env=env, check=True, timeout=180)


def contract(pointer):
    return {'format': 'cpg-alive-progress-private-prefix-v1', 'resource_id': 'py.alive-progress',
            'version': VERSION, 'source_sha256': SOURCE_SHA256, 'source_bytes': SOURCE_BYTES,
            'relative_private_root': '.cpg-wheel-layouts/' + LAYOUT_NAME, 'pth_name': PTH_NAME,
            'pth_content': pointer, 'original_wheel_modified': False}


def install(prefix, source):
    prefix, private, purelib, private_lib, pth, pointer = paths(prefix)
    source = Path(source).absolute()
    require(not source.is_symlink() and source.is_file(), 'Original wheel is not an ordinary file')
    require(source.stat().st_size == SOURCE_BYTES and digest(source) == SOURCE_SHA256,
            'Original alive-progress wheel identity differs')
    require(not private.exists() and not pth.exists() and not pth.is_symlink(),
            'Refusing to overwrite an existing private layout or .pth entry')
    try:
        importlib.metadata.distribution(NAME)
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise ValueError('Refusing an already visible alive-progress distribution')
    private.mkdir(parents=True)
    pip(['install', '--no-deps', '--no-index', '--no-cache-dir', '--no-compile', '--prefix', str(private), str(source)])
    inspected = inspect_distribution(private, private_lib)
    receipt = private / 'cpg-layout.json'
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(contract(pointer), stream, sort_keys=True, indent=2)
        stream.write('\n')
    with pth.open('x', encoding='utf-8') as stream:
        stream.write(pointer)
    require(digest(source) == SOURCE_SHA256 and source.stat().st_size == SOURCE_BYTES,
            'Original wheel changed during installation')
    print(json.dumps({'status': 'installed', 'private_prefix': str(private),
                      'retained_hashed_files': len(inspected['hashed_files']), 'original_wheel_modified': False}))


def remove(prefix):
    prefix, private, purelib, private_lib, pth, pointer = paths(prefix)
    ordinary_path(pth, prefix)
    require(pth.read_text() == pointer, 'Refusing removal with an altered .pth entry')
    receipt = ordinary_path(private / 'cpg-layout.json', private)
    require(json.loads(receipt.read_text()) == contract(pointer), 'Private layout contract was altered')
    inspected = inspect_distribution(private, private_lib)
    visible = importlib.metadata.distribution(NAME)
    require(Path(visible._path).absolute() == private_lib / 'alive_progress-3.3.0.dist-info',
            'Visible distribution is not the owned private installation')
    owned = [private / row['path'] for row in inspected['hashed_files']]
    pip(['uninstall', '--yes', NAME])
    require(all(not p.exists() for p in owned), 'pip left an originally hashed owned file')
    require(not (private_lib / 'alive_progress-3.3.0.dist-info').exists(), 'pip left the owned distribution metadata')
    pth.unlink()
    receipt.unlink()
    # Only remove empty directories; unrelated or unexpected content is retained.
    for directory in sorted([p for p in private.rglob('*') if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        private.rmdir()
    except OSError:
        pass
    print(json.dumps({'status': 'removed', 'private_prefix': str(private), 'original_hashed_files_absent': True,
                      'private_root_remaining': private.exists(), 'foreign_files_deleted': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['install', 'remove'])
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.operation == 'install':
        require(args.source is not None, 'Exact original wheel is required')
        install(args.prefix, args.source)
    else:
        require(args.source is None, 'Removal does not accept a source override')
        remove(args.prefix)


if __name__ == '__main__':
    main()
