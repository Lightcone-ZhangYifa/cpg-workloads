"""Bounded actual Python/native operations for the fixed 0.21.12 resources.

These probes exercise installed APIs. They make no claim of upstream source
compilation, remote services, OCI, or official benchmark qualification.
"""
from pathlib import Path
import asyncio
import importlib
import io
import json
import math
import os
import subprocess
import sys
from profile_probes import PROBES, main, require, raises


def alive_probe(module, work):
    output = io.StringIO()
    with module.alive_bar(3, file=output, force_tty=False, enrich_print=False) as bar:
        bar(); bar(2)
        require(bar.current == 3, "Progress count differs")
    require('3/3' in output.getvalue(), "Final progress receipt missing")
    values = list(module.alive_it([2, 3, 5], file=io.StringIO(), force_tty=False))
    require(values == [2, 3, 5], "Progress iterator changed data")
    try:
        with module.alive_bar(1, cpg_unknown_option=True):
            pass
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError("Unknown progress configuration accepted")
    return ['actual-progress-updates', 'final-receipt', 'iterator-preserves-data', 'unknown-option-rejection']


def hf_probe(module, work):
    import hashlib
    data = bytes(range(256)) * 9 + b'\x00xet\n'
    paths = [work / name for name in ('a', 'same', 'different')]
    for path, value in zip(paths, (data, data, data + b'_different')):
        path.write_bytes(value)
    native = Path(module.hf_xet.__file__).resolve()
    require(native.is_relative_to(Path(sys.prefix).resolve()) and native.read_bytes()[:4] == b'\x7fELF', 'Native library is not in the selected installation')
    results = module.hash_files([str(path) for path in paths])
    digests = [str(value.hash) for value in results]
    require(len(results) == 3 and digests[0] == digests[1] != digests[2], 'Native content hashing differs')
    require([value.file_size for value in results] == [len(data), len(data), len(data) + 10], 'Native byte counts differ')
    require(module.hash_files([]) == [], 'Empty input is not empty')
    raises(OSError, lambda: module.hash_files([str(work / 'missing')]), 'Missing input accepted')
    return {'checks': ['native-content-hashing', 'equal-and-different-inputs', 'exact-byte-counts', 'empty-input', 'missing-input'], 'native_sha256': hashlib.sha256(native.read_bytes()).hexdigest()}


def builder_probe(module, work):
    from jupyter_builder import jupyterlab_semver as semver
    from jupyter_builder.commands import _test_overlap
    require(semver.satisfies('1.4.2', '^1.2.0', False), 'Compatible version rejected')
    require(not semver.satisfies('2.0.0', '^1.2.0', False), 'Incompatible version accepted')
    require(_test_overlap('^1.2.0', '^1.4.0') is True, 'Overlapping build dependencies rejected')
    require(_test_overlap('^1.2.0', '^2.0.0') is False, 'Disjoint build dependencies overlap')
    raises(ValueError, lambda: semver.Range('not a version range', False), 'Malformed version range accepted')
    return ['actual-build-dependency-range-evaluation', 'compatible-and-incompatible-versions', 'range-intersection', 'malformed-range-rejection', 'no-Node-build-claim']


def lsp_probe(module, work):
    from jupyter_lsp.manager import LanguageServerManager
    from traitlets import TraitError
    spec = {'version': 2, 'argv': [sys.executable, '-u', '-c', 'pass'], 'languages': ['python']}
    manager = LanguageServerManager(autodetect=False, conf_d_language_servers={}, language_servers={'cpg-local': spec})
    manager.initialize()
    require(asyncio.run(manager.ready()) is True, 'Manager readiness failed')
    require(set(manager.sessions) == {'cpg-local'} and manager.sessions['cpg-local'].spec == spec, 'Configured session differs')
    require(manager.all_language_servers['cpg-local']['languages'] == ['python'], 'Language configuration differs')
    raises(TraitError, lambda: setattr(manager, 'language_servers', {'broken': {'argv': 17}}), 'Invalid language-server schema accepted')
    return ['actual-language-server-configuration', 'session-construction', 'async-readiness', 'schema-negative-case', 'no-language-server-execution-claim']


def lab_server_probe(module, work):
    from jupyterlab_server.config import get_federated_extensions, load_config
    root = work / 'extensions'; package = root / '@cpg' / 'sample'; package.mkdir(parents=True)
    metadata = {'name': '@cpg/sample', 'version': '1.2.3', 'description': 'local fixture', 'jupyterlab': {'extension': True}, 'homepage': 'https://example.invalid/cpg'}
    (package / 'package.json').write_text(json.dumps(metadata))
    (package / 'install.json').write_text(json.dumps({'packageManager': 'python', 'packageName': 'fixture'}))
    found = get_federated_extensions([str(root)])
    require(set(found) == {'@cpg/sample'} and found['@cpg/sample']['version'] == '1.2.3', 'Federated extension discovery differs')
    require(found['@cpg/sample']['install']['packageManager'] == 'python', 'Install metadata missing')
    path = work / 'page.json5'; path.write_text('// fixture\n{enabled: true, count: 3,}')
    require(load_config(str(path)) == {'enabled': True, 'count': 3}, 'JSON5 page configuration differs')
    path.write_text('{broken:')
    raises(ValueError, lambda: load_config(str(path)), 'Malformed configuration accepted')
    return ['real-federated-extension-discovery', 'scoped-extension-layout', 'installation-metadata', 'JSON5-config', 'malformed-config-rejection']


def ml_types_probe(module, work):
    import numpy as np
    array = np.array([1.0, 2.5, -4.0], dtype=module.bfloat16)
    require(array.dtype.itemsize == 2 and np.allclose(array.astype(np.float32), [1, 2.5, -4]), 'Bfloat16 conversion differs')
    require(np.allclose((array + array).astype(np.float32), [2, 5, -8]), 'Native bfloat16 arithmetic differs')
    small = np.array([0.5, 1, 2, -2], dtype=module.float8_e4m3fn)
    require(small.dtype.itemsize == 1 and np.allclose(small.astype(np.float32), [.5, 1, 2, -2]), 'Float8 roundtrip differs')
    path = work / 'typed.npy'; np.save(path, array, allow_pickle=False)
    loaded = np.load(path, allow_pickle=False)
    require(loaded.tobytes() == array.tobytes(), 'Typed storage bytes differ')
    info = module.finfo(module.bfloat16)
    require(float(info.eps) == 2 ** -7 and math.isfinite(float(info.max)), 'Native dtype limits differ')
    raises((TypeError, ValueError), lambda: module.finfo('cpg-not-a-dtype'), 'Invalid dtype accepted')
    return ['native-bfloat16-conversion', 'native-arithmetic', 'native-float8-conversion', 'exact-storage-bytes', 'type-limits', 'invalid-type-rejection']


def notebook_probe(module, work):
    import nbformat
    from nbclient import NotebookClient
    from nbclient.jsonutil import json_clean
    from nbclient.exceptions import CellExecutionError
    cell = nbformat.v4.new_code_cell('print(6 * 7)')
    notebook = nbformat.v4.new_notebook(cells=[cell])
    client = NotebookClient(notebook)
    message = {'header': {'msg_type': 'stream'}, 'msg_type': 'stream', 'content': {'name': 'stdout', 'text': '42\n'}, 'parent_header': {}}
    client.process_message(message, cell, 0)
    require(cell.outputs[0]['text'] == '42\n' and cell.outputs[0]['output_type'] == 'stream', 'Notebook output processing differs')
    normalized = json_clean({'tuple': (2, 3), 'infinite': float('inf')})
    require(normalized == {'tuple': [2, 3], 'infinite': 'inf'}, 'Notebook JSON normalization differs')
    raises(ValueError, lambda: json_clean({1: 'a', '1': 'b'}), 'Colliding notebook JSON keys accepted')
    error = CellExecutionError.from_cell_and_msg(cell, {'ename': 'ValueError', 'evalue': 'fixture', 'traceback': ['local traceback']})
    require('ValueError' in str(error) and 'fixture' in str(error), 'Execution error lost original details')
    nbformat.validate(notebook)
    return ['actual-notebook-output-state', 'notebook-format-validation', 'JSON-normalization', 'JSON-key-collision-rejection', 'execution-error-preservation', 'no-kernel-execution-claim']


def otel_probe(module, work):
    from opentelemetry.exporter.otlp.proto.common._internal import _encode_value, _encode_span_id
    require(_encode_value({'answer': 42}).kvlist_value.values[0].value.int_value == 42, 'OTLP value encoding differs')
    require(_encode_span_id(1) == b'\0' * 7 + b'\1', 'Span identifier encoding differs')
    raises(Exception, lambda: _encode_value(object()), 'Unsupported telemetry value accepted')
    return ['actual-OTLP-protobuf-values', 'span-ID-encoding', 'unsupported-value-rejection']


def polars_probe(module, work):
    series = module.PySeries.new_i64('values', [2, None, 3, 5], True)
    require(series.len() == 4 and series.null_count() == 1, 'Native series shape/null count differs')
    require(series.sum() == 10 and series.min() == 2 and series.max() == 5, 'Native aggregation differs')
    raises((TypeError, ValueError), lambda: module.PySeries.new_i64('bad', ['not-an-integer'], True), 'Invalid native integer accepted')
    return ['Rust-native-series-construction', 'nullable-values', 'sum-min-max', 'invalid-native-value', 'no-frontend-or-source-build-claim']


def pymoo_probe(module, work):
    import numpy as np
    from pymoo.problems import get_problem
    from pymoo.algorithms.soo.nonconvex.ga import GA
    from pymoo.optimize import minimize
    problem = get_problem('sphere', n_var=2)
    results = [minimize(problem, GA(pop_size=20), ('n_gen', 12), seed=17, verbose=False) for _ in range(2)]
    require(results[0].F.shape == (1,) and float(results[0].F[0]) < .05, 'Bounded optimizer failed known sphere objective')
    require(np.allclose(results[0].X, results[1].X) and np.allclose(results[0].F, results[1].F), 'Fixed-seed replay differs')
    require(np.allclose(problem.evaluate(results[0].X), results[0].F), 'Reported objective differs from actual problem evaluation')
    raises(Exception, lambda: get_problem('cpg-nonexistent-problem'), 'Unknown optimization problem accepted')
    return {'checks': ['actual-genetic-optimization', 'known-sphere-objective', 'fixed-seed-replay', 'independent-objective-check', 'unknown-problem-rejection'], 'objective': results[0].F.tolist()}


def tensorboard_probe(module, work):
    from tensorboard_wire import probe
    return probe(module, work)


def terminal_probe(module, work):
    from jupyter_server_terminals.terminalmanager import TerminalManager
    manager = TerminalManager(shell_command=[sys.executable, '-u', '-c', 'print(42)'])
    model = manager.create()
    require(model['name'] in manager.terminals, 'Terminal was not created')
    asyncio.run(manager.terminate(model['name'], force=True))
    require(model['name'] not in manager.terminals, 'Terminal did not terminate')
    return ['actual-PTY-creation', 'terminal-model', 'process-termination']


PROBES.update({'alive-progress': alive_probe, 'hf-xet': hf_probe, 'jupyter-builder': builder_probe,
               'jupyter-lsp': lsp_probe, 'jupyterlab-server': lab_server_probe, 'ml-dtypes': ml_types_probe,
               'nbclient': notebook_probe, 'opentelemetry-exporter-otlp-proto-common': otel_probe,
               'polars-runtime-32': polars_probe, 'pymoo': pymoo_probe,
               'tensorboard-data-server': tensorboard_probe, 'jupyter-server-terminals': terminal_probe})
