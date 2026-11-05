"""Complete ordinary source inventories, including exact internal symlinks."""
import hashlib
import os
from pathlib import Path
import stat
import re


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    rows = []
    inodes = set()
    for path in root.rglob('*'):
        info = path.lstat()
        row = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            assert path.resolve().is_relative_to(root.resolve()) and path.resolve().exists()
            row.update(kind='symlink', target=os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            assert info.st_nlink == 1 and (info.st_dev, info.st_ino) not in inodes
            inodes.add((info.st_dev, info.st_ino))
            row.update(kind='file', bytes=info.st_size, sha256=sha(path))
        else:
            assert stat.S_ISDIR(info.st_mode)
            row.update(kind='directory')
        rows.append(row)
    return sorted(rows, key=lambda row: row['path'])


def execution_matrix(text):
    """Read the unchanged Executor's explicit per-kernel support and run log."""
    kernel = variant = None
    supports, executed, kernels = {}, [], []
    for raw_line in text.splitlines():
        line = re.sub(r'^\d+: ', '', raw_line)
        found = re.match(r'^Run kernel -- (\S+)\s*$', line)
        if found:
            kernel, variant = found[1], None
            assert kernel not in kernels, 'Kernel appears twice in the one-pass execution log'
            kernels.append(kernel)
            continue
        found = re.match(r'^\s*(Running|No) (\S+) variant\s*$', line)
        if found:
            assert kernel is not None
            variant = found[2]
            key = (kernel, variant)
            assert key not in supports
            supports[key] = found[1] == 'Running'
            continue
        assert not re.match(r'^\s*Skipping \S+ tuning', line), 'A configured tuning was skipped'
        found = re.match(r'^\s*Running\s+(\S+)\s+tuning -- .* (PASSED|FAILED) checksum\s*$', line)
        if found:
            assert kernel is not None and variant is not None and supports[(kernel, variant)]
            assert found[2] == 'PASSED'
            key = (kernel, variant, found[1])
            assert key not in executed, 'Duplicate kernel/variant/tuning execution'
            executed.append(key)
    assert kernels and supports and executed
    assert {k[:2] for k in executed} == {k for k, value in supports.items() if value}
    return {'kernels': sorted(kernels), 'executed': sorted(map(list, executed)),
            'unsupported': sorted([list(key) for key, value in supports.items() if not value])}
