#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('--prefix', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
(a.output / 'result.json').unlink(missing_ok=True)
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('shardy_reference_index', a.prefix / 'index_tool.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
actual = module.create_index(a.prefix)
expected = json.loads((a.prefix / 'chapter-symbol-index.json').read_text())
checks = []
def require(name, condition):
    if not condition:
        raise RuntimeError(name)
    checks.append({'name': name, 'passed': True})
require('complete_index_recomputed_from_fixed_bytes', actual == expected)
require('official_overview_available', any(d['path'] == 'upstream/docs/overview.md' for d in actual['documents']))
require('version_pin', actual['source_commit'] == 'f7d73420eb7af1def1f7024db80256f7b8673651')
require('license_present', (a.prefix / 'upstream/LICENSE').is_file())
require('chapters_and_symbols_nonempty', len(actual['sections']) >= 20 and len(actual['symbols']) >= 10)
queries = {}
for term in ('TensorSharding', 'Mesh', 'ManualComputation', 'ShardingConstraint'):
    matches = [x for x in actual['symbols'] if term.casefold() in x['name'].casefold()]
    require('symbol_lookup_' + term, bool(matches))
    queries[term] = matches
(a.output / 'index-summary.json').write_text(json.dumps({
    'source_commit': actual['source_commit'], 'document_count': len(actual['documents']),
    'section_count': len(actual['sections']), 'symbol_count': len(actual['symbols']),
    'query_examples': queries}, indent=2))
result = {'status': 'passed', 'checks': checks, 'evidence_files': ['index-summary.json'],
          'functional_qualification': False,
          'scope': 'Pinned documentation and symbol/section lookup only.'}
(a.output / 'result.json').write_text(json.dumps(result, indent=2))
print('CPG_CHECK_PASS reference.shardy')
