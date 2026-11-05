"""Installed operations under an explicit, exact functional consumption closure."""
from __future__ import annotations
import argparse
import asyncio
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import traceback
from profile_probes import PROBES, require, raises, local_module
from consumption_guard import inspect_consumption


def otel_probe(module, work):
    from opentelemetry.exporter.otlp.proto.common._internal import _encode_value, _encode_span_id
    require(_encode_value({'answer': 42}).kvlist_value.values[0].value.int_value == 42, 'OTLP value encoding differs')
    require(_encode_span_id(1) == b'\0'*7+b'\1', 'Span identifier encoding differs')
    encoded = _encode_value([True, 3, 'cpg'])
    require(encoded.array_value.values[0].bool_value and encoded.array_value.values[1].int_value == 3 and
            encoded.array_value.values[2].string_value == 'cpg', 'Nested telemetry encoding differs')
    require(type(encoded).FromString(encoded.SerializeToString()) == encoded, 'Protobuf wire roundtrip differs')
    raises(Exception, lambda: _encode_value(object()), 'Unsupported telemetry value accepted')
    return ['actual-OTLP-protobuf-values', 'span-ID-encoding', 'nested-array-encoding', 'protobuf-wire-roundtrip', 'unsupported-value-rejection']


def soupsieve_probe(module, work):
    from bs4 import BeautifulSoup
    tree = BeautifulSoup('<main><ul><li class="a">first</li><li data-x="2">second</li><li class="a">third</li></ul></main>', 'html.parser')
    require([x.text for x in module.select('main > ul > li.a', tree)] == ['first', 'third'], 'Selector matching differs')
    require(module.select_one('li:nth-child(2)', tree)['data-x'] == '2', 'Positional selector differs')
    compiled = module.compile('li.a')
    require(compiled.match(tree.li) and [x.text for x in compiled.filter(tree.ul)] == ['first', 'third'], 'Compiled selector differs')
    raises(module.SelectorSyntaxError, lambda: module.compile('li['), 'Malformed selector accepted')
    require(module.select('aside', tree) == [], 'Missing selector returned matches')
    return ['actual-HTML-tree-consumption', 'CSS-selection', 'positional-selector', 'compiled-selector', 'malformed-selector-rejection', 'empty-match']


def terminal_probe(module, work):
    from jupyter_server_terminals.terminalmanager import TerminalManager
    from tornado.web import HTTPError
    async def exercise():
        # Creation and teardown must share Tornado's running asyncio loop;
        # its EOF handler removes the terminated terminal from the manager.
        manager = TerminalManager(shell_command=[sys.executable, '-I', '-u', '-c', 'import time; print(42,flush=True); time.sleep(5)'])
        try:
            model = manager.create()
            require(model['name'] in manager.terminals, 'Terminal was not created')
            terminal = manager.terminals[model['name']]
            require(terminal.ptyproc.isalive(), 'PTY child is not live')
            for _ in range(100):
                if '42' in ''.join(terminal.read_buffer): break
                await asyncio.sleep(.01)
            require('42' in ''.join(terminal.read_buffer), 'Actual terminal child output was not observed')
            await manager.terminate(model['name'], force=True)
            for _ in range(100):
                if model['name'] not in manager.terminals and not terminal.ptyproc.isalive(): break
                await asyncio.sleep(.01)
            require(model['name'] not in manager.terminals and not terminal.ptyproc.isalive(), 'Terminal did not terminate')
            raises(HTTPError, lambda: manager.get('cpg-nonexistent-terminal'), 'Missing terminal accepted')
        finally:
            await manager.terminate_all()
    asyncio.run(exercise())
    return ['actual-PTY-creation', 'terminal-model', 'live-child-output', 'forced-process-termination', 'same-loop-EOF-cleanup', 'unknown-terminal-rejection']


def inline_probe(module, work):
    import base64
    from IPython.core.interactiveshell import InteractiveShell
    from matplotlib_inline.backend_inline import new_figure_manager, set_matplotlib_formats, set_matplotlib_close
    from matplotlib_inline.config import InlineBackend
    from traitlets import TraitError
    shell = InteractiveShell.instance()
    manager = new_figure_manager(1, figsize=(2, 2), dpi=50)
    figure = manager.canvas.figure
    figure.add_subplot(111).plot([0, 1, 2], [0, 1, 4])
    try:
        set_matplotlib_formats('png', 'svg')
        payload, metadata = shell.display_formatter.format(figure)
        require('<svg' in payload['image/svg+xml'], 'Inline SVG representation missing')
        png = payload['image/png']
        if isinstance(png, str): png = base64.b64decode(png)
        require(png.startswith(b'\x89PNG\r\n\x1a\n'), 'Inline PNG representation differs')
        raises(ValueError, lambda: set_matplotlib_formats('cpg-invalid-format'), 'Unsupported figure format accepted')
        set_matplotlib_close(False)
        require(InlineBackend.instance().close_figures is False, 'Inline close policy did not persist')
        raises(TraitError, lambda: set_matplotlib_close('not-a-boolean'), 'Invalid close policy accepted')
        set_matplotlib_close(True)
    finally:
        manager.destroy()
        InteractiveShell.clear_instance()
        InlineBackend.clear_instance()
    return ['actual-inline-figure-manager', 'real-plot-data', 'PNG-display-payload', 'SVG-display-payload',
            'unsupported-format-rejection', 'inline-close-configuration', 'invalid-close-type-rejection']


def polars_probe(module, work):
    import numpy as np
    import polars
    require(Path(polars.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), 'Polars scalar consumer escaped the private prefix')
    series = module.PySeries.new_i64('values', np.array([2, 3, 5], dtype=np.int64), True)
    require(series.len() == 3 and series.null_count() == 0, 'Native series shape/null count differs')
    require(series.sum() == 10 and series.min() == 2 and series.max() == 5, 'Native aggregation differs')
    raises((TypeError, ValueError), lambda: module.PySeries.new_i64('bad', ['not-an-integer'], True), 'Invalid native integer accepted')
    return ['Rust-native-series-construction', 'exact-NumPy-consumption', 'exact-Polars-scalar-consumption', 'sum-min-max', 'invalid-native-value', 'no-source-build-claim']


PROBES.update({'opentelemetry-exporter-otlp-proto-common': otel_probe, 'soupsieve': soupsieve_probe,
               'jupyter-server-terminals': terminal_probe, 'polars-runtime-32': polars_probe,
               'matplotlib-inline': inline_probe})


def main(resource, distribution, module):
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--version-only', action='store_true')
    args = parser.parse_args()
    result = {'resource_id': resource, 'distribution': distribution, 'status': 'failed'}
    try:
        actual = importlib.metadata.version(distribution)
        require(actual == args.expected_version, 'Exact installed distribution version differs: '+actual)
        result['version'] = actual
        if not args.version_only:
            result['functional_consumption'] = inspect_consumption(Path(__file__).with_name('functional-consumption-lock.json'))
            mod = local_module(module)
            with tempfile.TemporaryDirectory(prefix='cpg-functional-', dir=Path.cwd()) as temporary:
                result['operations'] = PROBES[distribution.lower().replace('_','-')](mod, Path(temporary))
            result['module_file'] = str(Path(mod.__file__).resolve())
        result['status'] = 'passed'
    except BaseException as error:
        result.update(error=repr(error), traceback=traceback.format_exc())
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'passed' else 1
