import pathlib,sys,tempfile
from pyproject_hooks import BuildBackendHookCaller, BackendUnavailable
with tempfile.TemporaryDirectory(prefix='cpg-pep517-') as temp:
    root=pathlib.Path(temp)
    pkg=root/'backend';pkg.mkdir()
    (pkg/'tiny_cpg_backend.py').write_text('def get_requires_for_build_wheel(config_settings=None):\n    return ["cpg-local-protocol-ok"]\n')
    hooks=BuildBackendHookCaller(str(root),'tiny_cpg_backend',backend_path=['backend'],python_executable=sys.executable)
    assert hooks.get_requires_for_build_wheel() == ['cpg-local-protocol-ok']
    missing=BuildBackendHookCaller(str(root),'missing_cpg_backend',backend_path=['backend'],python_executable=sys.executable)
    try: missing.get_requires_for_build_wheel()
    except BackendUnavailable: pass
    else: raise AssertionError('missing backend unexpectedly available')
print('CPG_FUNCTIONAL_OK:pyproject-hooks:backend-subprocess-and-negative')
