"""Read only the exact execution inputs bound to one CPG installation."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value:
        raise ValueError('Unsafe execution profile path: ' + value)
    return value


class Profile:
    def __init__(self, assets, recipe):
        self.contract = json.loads((Path(recipe) / 'profile-contract.json').read_text())
        binding = json.loads((Path(assets) / 'profile-binding.json').read_text())
        self.root = Path(binding['root']).absolute()
        manifest = Path(recipe) / self.contract['manifest_file']
        if sha(manifest) != self.contract['manifest_sha256']:
            raise ValueError('Execution input manifest does not match the package recipe')
        self.manifest = json.loads(manifest.read_text())
        self.files = {r['path']: r for r in self.manifest['files']}
        self.definition = self.contract['resource']

    def path(self, name):
        name = relative(name)
        row = self.files.get(name)
        if row is None:
            raise ValueError('Execution input is not locked: ' + name)
        path = self.root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Execution input is not an ordinary file: ' + name)
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Execution input differs from its exact lock: ' + name)
        return path

    def validate_directories(self, names):
        count = 0
        for name in names:
            name = relative(name)
            prefix = name + '/'
            expected = {p for p in self.files if p.startswith(prefix)}
            if not expected:
                raise ValueError('Empty locked input selection: ' + name)
            for p in sorted(expected):
                self.path(p)
                count += 1
        return count

    def stage(self, names, destination):
        """Expose only the frozen input set to pip; extra raw files stay invisible."""
        destination = Path(destination)
        destination.mkdir()
        selected = [p for p in self.files if any(p.startswith(name + '/') for name in names)]
        for name in selected:
            source = self.path(name)
            target = destination / source.name
            if target.exists():
                if sha(target) != sha(source):
                    raise ValueError('Selected wheel filenames have different bytes')
            else:
                os.link(source, target)
        return destination
