"""Apply the reviewed stdout-format expectation change to a disposable source copy."""
import hashlib
import json
from pathlib import Path


def apply(source, declaration):
    source = Path(source).resolve()
    declaration = Path(declaration)
    data = json.loads(declaration.read_text())
    behavior = source / data['source_behavior']['path']
    if hashlib.sha256(behavior.read_bytes()).hexdigest() != data['source_behavior']['sha256']:
        raise ValueError('The reviewed XED source behavior changed')
    changed = []
    for row in data['tests']:
        path = source / row['path']
        if not path.resolve().is_relative_to(source) or not row['path'].endswith('/stdout.reference'):
            raise ValueError('Fixture path escapes the disposable source tree')
        original = path.read_bytes()
        if len(original) != row['original_bytes'] or hashlib.sha256(original).hexdigest() != row['original_sha256']:
            raise ValueError('Original test fixture identity changed: ' + row['path'])
        value = original.decode()
        for replacement in row['replacements']:
            before, after = replacement['before'], replacement['after']
            if value.splitlines().count(before) != 1:
                raise ValueError('Fixture transformation is ambiguous')
            value = '\n'.join(after if line == before else line for line in value.split('\n'))
        adapted = value.encode()
        if len(adapted) != row['adapted_bytes'] or hashlib.sha256(adapted).hexdigest() != row['adapted_sha256']:
            raise ValueError('Adapted fixture identity changed')
        path.write_bytes(adapted)
        changed.append({k: row[k] for k in ('path', 'original_sha256', 'original_bytes', 'adapted_sha256', 'adapted_bytes')})
    return {'status': 'passed', 'declaration_sha256': hashlib.sha256(declaration.read_bytes()).hexdigest(),
            'compiled_source_modified': False, 'test_driver_modified': False, 'exclusions_added': 0,
            'changed_fixtures': changed}
