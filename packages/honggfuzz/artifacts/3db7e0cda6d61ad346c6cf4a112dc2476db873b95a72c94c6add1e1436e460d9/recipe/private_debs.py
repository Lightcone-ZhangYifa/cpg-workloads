"""Unpack exact Debian inputs into one private tree without a host transaction."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def rel(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('Unsafe fixed Debian member')
    return Path(*[part for part in p.parts if part not in ('', '.')])


def extract(recipe, inputs, root, raw_destination, logs):
    root.mkdir(parents=True)
    raw_destination.mkdir(parents=True)
    logs.mkdir(parents=True, exist_ok=True)
    links, hardlinks, observed = {}, {}, []
    for row in inputs:
        raw = recipe / row['filename']
        if raw.stat().st_size != row['bytes'] or sha(raw) != row['sha256']:
            raise ValueError('Fixed Debian payload identity differs: ' + row['id'])
        identity = subprocess.run(['/usr/bin/dpkg-deb', '--field', str(raw), 'Package', 'Version', 'Architecture'],
                                  capture_output=True, text=True, check=True)
        actual = dict(line.split(': ', 1) for line in identity.stdout.splitlines())
        expected = {'Package': row['package_name'], 'Version': row['version'], 'Architecture': row['architecture']}
        if actual != expected:
            raise ValueError('Fixed Debian control metadata differs: ' + row['id'])
        shutil.copy2(raw, raw_destination / raw.name)
        count = 0
        with (logs / (row['id'] + '-decode.stderr')).open('wb') as stderr:
            process = subprocess.Popen(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(raw)], stdout=subprocess.PIPE,
                                       stderr=stderr, stdin=subprocess.DEVNULL)
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                for member in archive:
                    relative = rel(member.name)
                    if not relative.parts:
                        continue
                    path = root / relative
                    if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
                        raise ValueError('Debian entry writes through a link')
                    if member.isdir():
                        path.mkdir(parents=True, exist_ok=True)
                        path.chmod(member.mode & 0o777)
                    elif member.isfile():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as reader, path.open('wb') as writer:
                            shutil.copyfileobj(reader, writer)
                        path.chmod(member.mode & 0o777)
                        links.pop(relative.as_posix(), None)
                        hardlinks.pop(relative.as_posix(), None)
                    elif member.issym():
                        links[relative.as_posix()] = member.linkname
                    elif member.islnk():
                        hardlinks[relative.as_posix()] = rel(member.linkname).as_posix()
                    else:
                        raise ValueError('Unsupported Debian member kind')
                    count += 1
            process.stdout.close()
            if process.wait(timeout=30):
                raise RuntimeError('Debian archive decoder failed')
        observed.append({'id': row['id'], 'sha256': row['sha256'], 'bytes': row['bytes'], 'control': actual,
                         'decoded_members': count, 'original_url': row['url']})
    changes = []
    for name, original in sorted(links.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            if path.is_dir():
                raise ValueError('A Debian link would replace a directory')
            path.unlink()
        target = os.path.relpath(root / original.lstrip('/'), path.parent) if original.startswith('/') else original
        if not (path.parent / target).resolve().is_relative_to(root):
            raise ValueError('Private Debian link escapes its prefix')
        path.symlink_to(target)
        if target != original:
            changes.append({'path': name, 'original_target': original, 'installed_target': target})
    for name, target in sorted(hardlinks.items()):
        original = root / target
        if not original.is_file() or not original.resolve().is_relative_to(root):
            raise ValueError('Missing fixed Debian hardlink target')
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    unresolved = []
    for path in root.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError('Private runtime symlink escapes its root')
            if not path.exists():
                unresolved.append({'path': path.relative_to(root).as_posix(), 'target': os.readlink(path)})
    if unresolved:
        raise ValueError('The exact private closure has unresolved links: ' + repr(unresolved))
    return {'status': 'passed', 'inputs': observed, 'absolute_link_relocations': changes,
            'host_apt_transaction': 'not_run', 'maintainer_scripts_executed': False}
