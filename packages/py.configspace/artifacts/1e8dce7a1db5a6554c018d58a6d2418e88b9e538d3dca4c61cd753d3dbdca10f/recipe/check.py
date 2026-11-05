#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(cs, work):
    """Check bounded sampling, conditional/forbidden domains and JSON preservation."""
    space = cs.ConfigurationSpace(seed=123)
    optimizer = cs.Categorical('optimizer',['sgd','adam'],default='sgd')
    rate = cs.Float('rate',(0.0001,0.1),default=0.01,log=True)
    momentum = cs.Float('momentum',(0.0,0.99),default=0.9)
    batch = cs.Integer('batch',(8,64),default=16)
    space.add([optimizer,rate,momentum,batch]); space.add(cs.EqualsCondition(momentum,optimizer,'sgd'))
    space.add(cs.ForbiddenAndConjunction(cs.ForbiddenEqualsClause(optimizer,'adam'),cs.ForbiddenEqualsClause(batch,8)))
    configurations = space.sample_configuration(64)
    require(len(configurations) == 64, 'Sample count mismatch')
    for configuration in configurations:
        values = dict(configuration)
        require(8 <= values['batch'] <= 64 and 0.0001 <= values['rate'] <= 0.1, 'Sample outside bounds')
        require(('momentum' in values) == (values['optimizer'] == 'sgd'), 'Conditional hyperparameter activation wrong')
        require(not (values['optimizer'] == 'adam' and values['batch'] == 8), 'Forbidden sample produced')
        configuration.check_valid_configuration()
    space.seed(17); first = [dict(x) for x in space.sample_configuration(5)]
    space.seed(17); second = [dict(x) for x in space.sample_configuration(5)]
    require(first == second, 'Seeded sampling was not reproducible')
    destination = work/'space.json'; space.to_json(destination)
    restored = cs.ConfigurationSpace.from_json(destination)
    require(set(restored.keys()) == set(space.keys()) and dict(restored.get_default_configuration()) == dict(space.get_default_configuration()), 'Configuration-space JSON round trip failed')
    raises(ValueError, lambda: cs.Configuration(space,values={'optimizer':'adam','rate':0.01,'batch':8}), 'Forbidden configuration accepted')
    raises(ValueError, lambda: cs.Configuration(space,values={'optimizer':'sgd','rate':0.01,'momentum':0.9,'batch':100}), 'Out-of-domain value accepted')
    return {'checks':['64-bounded-samples','conditional-activation','forbidden-combination','configuration-validation','seed-reproducibility','json-roundtrip','forbidden-error','domain-error'], 'sample_count':64}

if __name__ == "__main__":
    raise SystemExit(main('configspace', 'ConfigSpace', functional))
