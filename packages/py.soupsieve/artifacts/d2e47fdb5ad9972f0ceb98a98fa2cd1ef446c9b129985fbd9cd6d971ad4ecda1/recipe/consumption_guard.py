"""Require the exact explicitly locked installed functional consumption closure."""
from __future__ import annotations
import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


def inspect_consumption(lock_path):
    lock = json.loads(Path(lock_path).read_text())
    prefix = Path(sys.prefix).resolve()
    assert sys.prefix != sys.base_prefix, 'A private environment is required'
    config = (prefix/'pyvenv.cfg').read_text().lower()
    assert 'include-system-site-packages = false' in config, 'Host site-packages are forbidden'
    rows = []
    for row in lock['resources']:
        dist = importlib.metadata.distribution(row['distribution'])
        assert dist.version == row['version'], ('consumption_version_mismatch', row['id'], dist.version)
        metadata = Path(dist._path)
        assert metadata.is_dir() and not metadata.is_symlink() and metadata.resolve().is_relative_to(prefix)
        files = dist.files
        assert files, ('missing_consumption_RECORD', row['id'])
        direct = json.loads(dist.read_text('direct_url.json'))
        expected = row['source']['sha256']
        assert direct['archive_info']['hashes']['sha256'] == expected
        assert direct['archive_info'].get('hash') == 'sha256='+expected
        count = 0
        for item in files:
            path = Path(dist.locate_file(item))
            assert path.resolve().is_relative_to(prefix), ('consumption_path_escape', row['id'], str(path))
            assert not path.is_symlink() and path.is_file() and path.stat().st_nlink == 1
            if item.hash:
                with path.open('rb') as stream: digest = hashlib.file_digest(stream, item.hash.mode).digest()
                assert base64.urlsafe_b64encode(digest).decode().rstrip('=') == item.hash.value
                assert item.size is None or item.size == path.stat().st_size
                count += 1
        assert count
        rows.append({'id': row['id'], 'version': dist.version, 'hashed_files': count,
                     'original_wheel_sha256': expected, 'metadata_path': str(metadata.resolve())})
    return {'status': 'passed', 'resources': rows, 'consumer_roots': lock['consumer_roots'],
            'support_qualifications': 0}
