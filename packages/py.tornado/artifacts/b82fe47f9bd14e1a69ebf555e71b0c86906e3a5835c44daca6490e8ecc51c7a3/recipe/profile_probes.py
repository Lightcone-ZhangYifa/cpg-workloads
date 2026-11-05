"""Bounded operations for the exact installed distribution in one private prefix.

This recipe helper does not acquire, install or modify any external resource.
Each probe returns its actual semantic checks; the maintainer controller owns
separate RECORD, copy-isolation, mutation and uninstall validation.
"""
from __future__ import annotations
import argparse
import asyncio
import importlib
import importlib.metadata
import io
import json
import os
import operator
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import traceback


def require(value, message):
    if not value:
        raise AssertionError(message)


def raises(exception, operation, message):
    try:
        operation()
    except exception:
        return
    raise AssertionError(message)


def local_module(name):
    module = importlib.import_module(name)
    origin = getattr(module, '__file__', None)
    require(origin and Path(origin).resolve().is_relative_to(Path(sys.prefix).resolve()),
            'Module is outside the selected private prefix: ' + name)
    return module


def probe_dill(dill, work):
    def factory(delta):
        return lambda value: value + delta
    target = factory(7)
    restored = dill.loads(dill.dumps(target))
    require(restored(11) == 18 and restored(-3) == 4, 'Captured closure round trip failed')
    value = {'closure': target, 'tuple': (1, 'compiler', None), 'set': {2, 4}}
    stream = io.BytesIO(); dill.dump(value, stream); stream.seek(0)
    copy = dill.load(stream)
    require(copy['closure'](0) == 7 and copy['tuple'] == value['tuple'] and copy['set'] == {2, 4},
            'Structured stream round trip failed')
    import pickle
    raises((pickle.UnpicklingError, EOFError), lambda: dill.loads(b'not-a-pickle'), 'Corrupt serialized data accepted')
    return {'checks': ['captured-closure-roundtrip', 'structured-stream-roundtrip', 'corrupt-data-rejection']}


def probe_frozenlist(module, work):
    values = module.FrozenList([1, 2]); values.append(3)
    require(list(values) == [1, 2, 3] and not values.frozen, 'Mutable list operations failed')
    values.freeze(); require(values.frozen, 'Freeze state did not change')
    raises(RuntimeError, lambda: values.append(4), 'Frozen append accepted')
    raises(RuntimeError, lambda: values.__setitem__(0, 9), 'Frozen assignment accepted')
    same = module.FrozenList([1, 2, 3]); same.freeze()
    require(values == same and hash(values) == hash(same), 'Frozen value/hash equality failed')
    return {'checks': ['mutable-append', 'freeze-state', 'frozen-append-rejection', 'frozen-assignment-rejection', 'frozen-hash-equality']}


def probe_multidict(module, work):
    values = module.MultiDict([('seed', '1'), ('seed', '3')]); values.add('seed', '5')
    require(values.getall('seed') == ['1', '3', '5'], 'Duplicate-key order failed')
    view = module.MultiDictProxy(values)
    values.add('other', 'visible'); require(view['other'] == 'visible', 'Read-only view lost backing changes')
    raises(TypeError, lambda: operator.setitem(view, 'x', 'y'), 'Proxy mutation accepted')
    headers = module.CIMultiDict([('Content-Type', 'text/plain'), ('X-Test', 'a')])
    require(headers['content-type'] == 'text/plain' and headers['X-TEST'] == 'a', 'Case-insensitive lookup failed')
    raises(KeyError, lambda: values['absent'], 'Missing key accepted')
    return {'checks': ['ordered-duplicate-values', 'backed-read-only-view', 'proxy-mutation-rejection', 'case-insensitive-headers', 'missing-key-rejection']}


def probe_propcache(module, work):
    api = local_module('propcache.api')
    class Value:
        def __init__(self): self.calls = 0
        @api.cached_property
        def result(self):
            self.calls += 1
            return self.calls * 7
    item = Value()
    require(item.result == item.result == 7 and item.calls == 1, 'Cached computation repeated')
    del item.result
    require(item.result == 14 and item.calls == 2, 'Explicit cache invalidation failed')
    other = Value(); require(other.result == 7 and other.calls == 1, 'Instances share cache state')
    return {'checks': ['single-cached-computation', 'delete-invalidates-cache', 'independent-instance-cache']}


def probe_rpds(module, work):
    original = module.HashTrieMap({'a': 1, 'b': 2}); changed = original.insert('a', 9)
    require(original['a'] == 1 and changed['a'] == 9, 'Persistent map changed its parent')
    removed = changed.remove('b'); require('b' in changed and 'b' not in removed, 'Persistent removal failed')
    raises(KeyError, lambda: original['missing'], 'Missing key accepted')
    values = module.HashTrieSet([1, 2]); added = values.insert(3)
    require(3 not in values and 3 in added, 'Persistent set insertion changed its parent')
    return {'checks': ['persistent-map-update', 'persistent-map-removal', 'missing-key-rejection', 'persistent-set-independence']}


def probe_regress(module, work):
    expression = module.Regex(r'(?<word>[A-Z]+)-(?<number>\d+)', 'i')
    text = 'prefix Abc-17 and xyz-42 suffix'
    match = expression.find(text)
    require(match is not None and text[match.range()] == 'Abc-17', 'Pattern match range failed')
    require(text[match.named_group('word')] == 'Abc' and text[match.named_group('number')] == '17', 'Named captures failed')
    require([text[item.range()] for item in expression.find_iter(text)] == ['Abc-17', 'xyz-42'], 'Iterated matches failed')
    require(expression.find('no-match') is None, 'No-match result failed')
    raises(module.RegressError, lambda: module.Regex('('), 'Malformed expression accepted')
    return {'checks': ['ecmascript-pattern-range', 'named-captures', 'ordered-match-iteration', 'no-match', 'invalid-pattern-rejection']}


def probe_ruamel(module, work):
    yaml = module.YAML(typ='safe')
    value = {'compiler': '中文', 'seeds': [1, 3, 5], 'enabled': True}
    stream = io.StringIO(); yaml.dump(value, stream)
    require(yaml.load(stream.getvalue()) == value, 'Safe YAML round trip failed')
    require(list(yaml.load_all('a: 1\n---\nb: 2\n')) == [{'a': 1}, {'b': 2}], 'Multiple documents failed')
    raises(module.YAMLError, lambda: yaml.load('a: [1, 2'), 'Malformed YAML accepted')
    raises(module.YAMLError, lambda: yaml.load('!!python/object/apply:builtins.str [1]'), 'Executable Python tag accepted')
    return {'checks': ['safe-unicode-roundtrip', 'multiple-documents', 'malformed-yaml-rejection', 'python-tag-rejection']}


def probe_tqdm(module, work):
    stream = io.StringIO()
    with module.tqdm(total=4, file=stream, mininterval=0, miniters=1, leave=True, desc='cpg') as bar:
        bar.update(1); bar.update(3)
        require(bar.n == 4 and bar.total == 4, 'Manual progress count failed')
    require('4/4' in stream.getvalue() and 'cpg' in stream.getvalue(), 'Progress output missing final count')
    require(list(module.tqdm(range(5), disable=True)) == list(range(5)), 'Iterable wrapper changed data')
    raises(module.TqdmKeyError, lambda: module.tqdm(cpg_unknown_argument=True), 'Unknown argument accepted')
    return {'checks': ['manual-progress-count', 'captured-final-output', 'iterable-preservation', 'unknown-argument-rejection']}


def probe_traitlets(module, work):
    class Config(module.HasTraits):
        count = module.Int(0)
        name = module.Unicode('compiler')
    config = Config(); events = []
    config.observe(lambda change: events.append((change['old'], change['new'])), names='count')
    config.count = 4
    require(config.count == 4 and events == [(0, 4)], 'Validated value/observer failed')
    raises(module.TraitError, lambda: setattr(config, 'count', 'invalid'), 'Invalid integer trait accepted')
    require(config.count == 4 and events == [(0, 4)], 'Rejected assignment changed state')
    second = Config(); require(second.count == 0 and second.name == 'compiler', 'Default instance state leaked')
    return {'checks': ['typed-assignment', 'observer-old-new', 'invalid-type-rejection', 'failure-preserves-state', 'independent-defaults']}


def probe_urllib3(module, work):
    from http_fixture import local_server
    with local_server() as base:
        pool = module.PoolManager(timeout=module.Timeout(connect=2, read=2), retries=False)
        try:
            response = pool.request('GET', base + '/ok?q=compiler', headers={'X-Check': 'verified'})
            require(response.status == 200 and response.json() == {'path': '/ok?q=compiler', 'header': 'verified'}, 'HTTP query/header response failed')
            payload = {'values': [1, 2, 3]}
            posted = pool.request('POST', base + '/echo', body=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            require(posted.json() == payload, 'JSON body round trip failed')
            compressed = pool.request('GET', base + '/gzip')
            require(compressed.json() == {'compressed': True}, 'Gzip decoding failed')
            error = pool.request('GET', base + '/error')
            require(error.status == 503, 'HTTP error status was hidden')
            raises(ValueError, lambda: module.Timeout(total=-1), 'Invalid timeout accepted')
            raises(module.exceptions.LocationParseError, lambda: module.util.parse_url('http://[broken'), 'Malformed address accepted')
        finally:
            pool.clear()
    return {'checks': ['loopback-get-query-header', 'json-post-roundtrip', 'gzip-decoding', 'status-propagation', 'invalid-timeout-rejection', 'malformed-address-rejection', 'closed-pool-and-server'], 'scope': 'Local HTTP only; no live remote TLS or proxy qualification.'}


def probe_wrapt(module, work):
    calls = []
    @module.decorator
    def traced(wrapped, instance, args, kwargs):
        calls.append((instance is None, tuple(args), dict(kwargs)))
        return wrapped(*args, **kwargs) + 1
    @traced
    def add(left, right=0): return left + right
    require(add(3, right=4) == 8 and add.__wrapped__(3, right=4) == 7, 'Function wrapping failed')
    class Value:
        @traced
        def add(self, value): return value + 10
    require(Value().add(5) == 16 and calls[-1][0] is False, 'Bound method wrapping failed')
    original = {'a': 1}; proxy = module.ObjectProxy(original); proxy['b'] = 2
    require(original == {'a': 1, 'b': 2} and proxy.__wrapped__ is original, 'Object proxy forwarding failed')
    raises(TypeError, lambda: add(), 'Wrapped missing argument accepted')
    return {'checks': ['decorated-function-result', 'wrapped-original-access', 'bound-method-context', 'object-proxy-forwarding', 'argument-error-propagation']}


def probe_tornado(module, work):
    ioloop = local_module('tornado.ioloop'); queues = local_module('tornado.queues'); locks = local_module('tornado.locks')
    async def run():
        queue = queues.Queue(maxsize=2)
        await queue.put(3); await queue.put(5)
        first = await queue.get(); queue.task_done()
        second = await queue.get(); queue.task_done(); await queue.join()
        require((first, second) == (3, 5), 'Queue ordering failed')
        raises(queues.QueueEmpty, queue.get_nowait, 'Empty queue accepted')
        lock = locks.Lock(); observed = []
        async with lock:
            observed.append('held')
        async with lock:
            observed.append('reacquired')
        require(observed == ['held', 'reacquired'], 'Async lock lifecycle failed')
        event = locks.Event(); event.set(); await event.wait(); event.clear()
        require(not event.is_set(), 'Event clear failed')
    loop = ioloop.IOLoop()
    try: loop.run_sync(run, timeout=5)
    finally: loop.close(all_fds=True)
    return {'checks': ['real-event-loop', 'async-fifo-and-join', 'empty-queue-rejection', 'async-lock-release-reacquire', 'event-set-wait-clear'], 'scope': 'Local event-loop, queues and synchronization; no remote HTTP server qualification.'}


def probe_executing(module, work):
    import ast
    fixture = work / 'source_fixture.py'
    fixture.write_text('value = 6\nresult = value * 7\n', encoding='utf-8')
    source = module.Source.for_filename(str(fixture))
    require(source.text == fixture.read_text() and isinstance(source.tree, ast.Module), 'Source parsing failed')
    assignments = [node for node in ast.walk(source.tree) if isinstance(node, ast.Assign)]
    require(len(assignments) == 2 and len(source.statements_at_line(2)) == 1, 'Statement/line mapping failed')
    observed = module.Source.executing(sys._getframe())
    require(observed.node is not None and isinstance(observed.node, ast.Call), 'Live frame call-node resolution failed')
    require(Path(observed.source.filename).resolve() == Path(__file__).resolve(), 'Live frame resolved the wrong source')
    return {'checks': ['source-parse-and-content', 'assignment-line-mapping', 'live-frame-call-node', 'live-frame-source-identity']}


def probe_nanobind(module, work):
    include = Path(module.include_dir()).resolve()
    root = include.parent
    require(include.is_relative_to(Path(sys.prefix).resolve()), 'Nanobind headers are outside private prefix')
    runtime = root / 'src/nb_combined.cpp'
    robin = root / 'ext/robin_map/include'
    require(runtime.is_file() and robin.is_dir(), 'Nanobind compile inputs missing')
    source = work / 'binding.cpp'
    source.write_text('#include <nanobind/nanobind.h>\nnamespace nb = nanobind;\nNB_MODULE(cpg_nb_probe, m) { m.def("add", [](int a, int b) { return a+b; }); }\n')
    suffix = sysconfig.get_config_var('EXT_SUFFIX')
    output = work / ('cpg_nb_probe' + suffix)
    argv = ['c++', '-std=c++17', '-O0', '-shared', '-fPIC', '-fvisibility=hidden', '-DNB_COMPACT_ASSERTIONS',
            '-I' + str(include), '-I' + str(robin), '-I' + sysconfig.get_path('include'), str(source), str(runtime), '-o', str(output)]
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    require(completed.returncode == 0, 'Nanobind extension compile failed: ' + completed.stderr[-4000:])
    code = 'import importlib.util,sys\nspec=importlib.util.spec_from_file_location("cpg_nb_probe",sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nassert m.add(5,7)==12\nassert m.add(-3,1)==-2\ntry:m.add("bad",1)\nexcept TypeError:pass\nelse:raise AssertionError("invalid input accepted")\nprint("binding-pass")\n'
    probe = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(output)], capture_output=True, text=True, timeout=20)
    require(probe.returncode == 0 and probe.stdout == 'binding-pass\n', 'Compiled extension execution failed: ' + probe.stderr[-3000:])
    return {'checks': ['private-header-and-runtime-inputs', 'actual-cpp-extension-compilation', 'native-call-results', 'native-argument-error'],
            'compile_argv': argv, 'native_output_bytes': output.stat().st_size,
            'scope': 'One local C++17 Python extension; no upstream nanobind suite or cross-platform qualification.'}


PROBES = {
    'dill': probe_dill, 'frozenlist': probe_frozenlist, 'multidict': probe_multidict,
    'propcache': probe_propcache, 'rpds': probe_rpds, 'regress': probe_regress, 'ruamel.yaml': probe_ruamel,
    'tqdm': probe_tqdm, 'traitlets': probe_traitlets, 'urllib3': probe_urllib3,
    'wrapt': probe_wrapt, 'tornado': probe_tornado, 'executing': probe_executing,
    'nanobind': probe_nanobind,
}


def main(resource_id, distribution, module_name):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--version-only', action='store_true')
    args = parser.parse_args()
    report = {'status': 'failed', 'resource_id': resource_id, 'distribution': distribution,
              'version': args.expected_version, 'interpreter': sys.executable}
    try:
        dist = importlib.metadata.distribution(distribution)
        require(dist.version == args.expected_version, 'Exact distribution version mismatch')
        require(Path(dist.locate_file('')).resolve().is_relative_to(Path(sys.prefix).resolve()), 'Distribution is outside private prefix')
        module = local_module(module_name)
        report['module_location'] = module.__file__
        report['prefix'] = sys.prefix
        if args.version_only:
            report['checks'] = ['exact-distribution-and-private-module-location']
        else:
            with tempfile.TemporaryDirectory(prefix='cpg-python-operation-', dir=Path.cwd()) as temporary:
                details = PROBES[module_name](module, Path(temporary))
            require(isinstance(details, dict) and details.get('checks'), 'Empty functional observation cannot pass')
            report.update(details)
        report['status'] = 'passed'
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'passed' else 1
