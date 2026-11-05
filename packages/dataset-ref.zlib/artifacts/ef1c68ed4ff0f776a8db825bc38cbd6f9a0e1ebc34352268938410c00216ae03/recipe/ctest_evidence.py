"""Require an exact, nonempty CTest execution record before qualification.

A successful ctest process alone does not establish that selected tests ran.
This helper binds the show-only list to the JUnit records without accepting
skipped, disabled, duplicate, missing, or failing cases.
"""
from __future__ import annotations
from collections import Counter
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def validate_ctest_evidence(list_path: Path, junit_path: Path) -> dict:
    listing = json.loads(list_path.read_text(encoding='utf-8'))
    rows = listing.get('tests')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Upstream CTest selection must be nonempty')
    selected = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name']:
            raise ValueError('Invalid selected CTest name')
        selected.append(row['name'])
        for prop in row.get('properties', []):
            if prop.get('name') == 'DISABLED' and prop.get('value') not in (False, 0, '0', 'FALSE', 'OFF'):
                raise ValueError('A selected upstream test is disabled')
    if len(set(selected)) != len(selected):
        raise ValueError('Selected upstream test names must be unique')
    xml = ET.parse(junit_path).getroot()
    if xml.tag not in {'testsuite', 'testsuites'}:
        raise ValueError('Unexpected CTest JUnit root')
    cases = list(xml.iter('testcase'))
    names = [case.get('name') for case in cases]
    if Counter(names) != Counter(selected):
        raise ValueError('CTest JUnit cases do not exactly match the selected tests')
    for case in cases:
        if case.get('status') != 'run':
            raise ValueError('A selected upstream test did not run')
        if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
            raise ValueError('A selected upstream test failed or was skipped')
        try:
            seconds = float(case.attrib['time'])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError('Missing or invalid upstream test duration') from error
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid upstream test duration')
    # CTest emits one suite. Nested suites are accepted only if each suite's
    # declared counters agree with its direct cases; aggregate totals on a
    # testsuites wrapper are validated independently when present.
    for suite in xml.iter('testsuite'):
        direct = list(suite.findall('testcase'))
        if list(suite.findall('testsuite')):
            raise ValueError('Nested testsuite counters are ambiguous')
        try:
            if int(suite.attrib['tests']) != len(direct):
                raise ValueError('CTest suite count disagrees with its cases')
            for key in ('failures', 'errors', 'skipped', 'disabled'):
                if int(suite.get(key, '0')) != 0:
                    raise ValueError('CTest suite reports failures or unexecuted tests')
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid CTest suite counters') from error
    if xml.tag == 'testsuites':
        for key, expected in (('tests', len(cases)), ('failures', 0), ('errors', 0), ('skipped', 0), ('disabled', 0)):
            if key in xml.attrib:
                try:
                    if int(xml.attrib[key]) != expected:
                        raise ValueError('Unexpected aggregate CTest count')
                except (TypeError, ValueError) as error:
                    raise ValueError('Invalid aggregate CTest count') from error
    return {'status': 'passed', 'listed': len(selected), 'executed': len(cases),
            'failures': 0, 'errors': 0, 'skipped': 0, 'names': sorted(selected)}
