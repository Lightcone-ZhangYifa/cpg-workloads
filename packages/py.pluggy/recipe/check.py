#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pluggy, work):
    """Check hook registration, wrapper composition, removal and signature errors."""
    hookspec = pluggy.HookspecMarker('cpg'); hookimpl = pluggy.HookimplMarker('cpg')
    class Spec:
        @hookspec
        def score(self,value): pass
    class Add:
        @hookimpl
        def score(self,value): return value+1
    class Multiply:
        @hookimpl
        def score(self,value): return value*2
    class Wrapper:
        @hookimpl(wrapper=True)
        def score(self,value):
            results = yield
            return [result+10 for result in results]
    manager = pluggy.PluginManager('cpg'); manager.add_hookspecs(Spec)
    add = Add(); multiply = Multiply()
    manager.register(add,name='add'); manager.register(multiply,name='multiply')
    require(sorted(manager.hook.score(value=3)) == [4,6], 'Hook results wrong')
    manager.register(Wrapper(),name='wrapper')
    require(sorted(manager.hook.score(value=3)) == [14,16], 'Wrapper composition failed')
    manager.unregister(multiply)
    require(manager.hook.score(value=3) == [14] and not manager.has_plugin('multiply'), 'Unregister failed')
    raises(ValueError, lambda: manager.register(add,name='duplicate'), 'Duplicate plugin accepted')
    class Bad:
        @hookimpl
        def score(self,unknown): return unknown
    raises(pluggy.PluginValidationError, lambda: manager.register(Bad(),name='bad'), 'Incompatible hook signature accepted')
    return {'checks':['registered-hook-calls','multiple-results','wrapper-composition','unregister','plugin-identity','duplicate-plugin','signature-error']}

if __name__ == "__main__":
    raise SystemExit(main('pluggy', 'pluggy', functional))
