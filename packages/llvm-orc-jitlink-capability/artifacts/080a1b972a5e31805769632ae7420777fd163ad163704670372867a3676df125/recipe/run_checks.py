#!/usr/bin/env python3
"""Run the bounded, relocatable LLVM ORC/JITLink profile offline."""
import json
from pathlib import Path
import platform
import subprocess

root = Path(__file__).resolve().parent
if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
    raise SystemExit('This binary profile was built for Linux x86_64.')
cases = [
    ('LLJITWithCustomObjectLinkingLayer', ['add1(42) = 43']),
    ('LLJITWithSymbolAliases', ['aliased_foo() = 42', 'aliased_bar() = 7']),
    ('cpg-orc-jitlink', ['ORC_JITLINK_PASS cases=2001 host_calls=2001',
                       'missing_symbol_rejected=1 removed_symbol_absent=1']),
]
results = []
for name, expected in cases:
    r = subprocess.run([str(root/'bin'/name)], capture_output=True, text=True,
                       timeout=120)
    if r.returncode or any(s not in r.stdout for s in expected):
        raise RuntimeError(json.dumps({'name': name, 'returncode': r.returncode,
                                      'stdout': r.stdout, 'stderr': r.stderr}))
    results.append({'name': name, 'returncode': r.returncode, 'stdout': r.stdout})
print(json.dumps({'status': 'passed', 'network_used': False,
                  'parent_resource': 'llvm-release',
                  'llvm_commit': '7a941dfb2877a0b8cf30323fefa85ad019e0b0f5',
                  'full_llvm_source_build': False,
                  'profile': 'ORC/JITLink with the official 23.1.4 prebuilt SDK',
                  'results': results}, indent=2))
