from __future__ import annotations
import argparse, json, os, pathlib, pickle, sys, time
from benchmark import Benchmark, DEFAULT, EvaluationError, clean_config, InvalidConfiguration
SEED = 83

def write(out, doc):
    (out / 'result.json').write_text(json.dumps(doc, indent=2, allow_nan=False) + '\n')
    print(json.dumps(doc, allow_nan=False))

def legal_ng(c):
    return c["opt"] != 1 or c["unroll"] == 0

def nevergrad_run(out):
    import nevergrad as ng
    p = ng.p.Dict(opt=ng.p.Choice([1, 2, 3]), tile=ng.p.Choice([4, 8, 16, 32]), unroll=ng.p.Choice([0, 1]), vectorize=ng.p.Choice([0, 1]))
    p.random_state.seed(SEED)
    p.register_cheap_constraint(legal_ng)
    opt = ng.optimizers.NGOpt(parametrization=p, budget=16, num_workers=1)
    b = Benchmark(out, 'nevergrad')
    seen = []
    for i in range(16):
        cand = opt.ask()
        c = clean_config(cand.value)
        v = b.evaluate(c, trial_id=cand.uid)
        opt.tell(cand, v)
        seen.append({'uid': cand.uid, 'configuration': c, 'objective_seconds': v})
    recommendation = clean_config(opt.provide_recommendation().value)
    if not opt.num_ask == opt.num_tell == 16:
        raise RuntimeError('Required validation failed')
    opt.dump(str(out / 'optimizer.pkl'))
    write(out, {'status': 'passed', 'tool': 'nevergrad', 'version': ng.__version__, 'seed': SEED, 'budget': 16, 'num_ask': opt.num_ask, 'num_tell': opt.num_tell, 'trials': seen, 'recommendation': recommendation, 'recommendation_train_seconds': b.evaluate(recommendation, phase='recommendation_replay'), 'replay': b.replay(recommendation)})

def optuna_run(out, phase):
    import optuna
    storage = 'sqlite:///' + str(out / 'study.sqlite3')
    name = 'cpg-real-compile-083'
    b = Benchmark(out, 'optuna')

    def objective(trial):
        opt = trial.suggest_categorical('opt', [1, 2, 3])
        c = {'opt': opt, 'tile': trial.suggest_categorical('tile', [4, 8, 16, 32]), 'unroll': trial.suggest_categorical('unroll', [0, 1]) if opt >= 2 else 0, 'vectorize': trial.suggest_categorical('vectorize', [0, 1])}
        trial.set_user_attr('measured_config', c)
        trial.set_user_attr('instance', 'train-a')
        return b.evaluate(c, fault=trial.user_attrs.get('fault'), trial_id=trial.number)
    if phase == 'start':
        s = optuna.create_study(study_name=name, storage=storage, direction='minimize', sampler=optuna.samplers.TPESampler(seed=SEED))
        for fault in ['FAULT_COMPILE', 'FAULT_TIMEOUT', 'FAULT_WRONG']:
            s.enqueue_trial(DEFAULT, user_attrs={'fault': fault})
        s.optimize(objective, n_trials=9, catch=(EvaluationError,))
        rows = [{'number': t.number, 'value': t.value, 'state': t.state.name, 'params': t.params} for t in s.trials]
        (out / 'phase1.json').write_text(json.dumps(rows, indent=2))
        if not (len(rows) == 9 and sum((t['state'] == 'FAIL' for t in rows)) == 3):
            raise RuntimeError('Required validation failed')
        print(json.dumps({'phase': 'start', 'persisted': len(rows), 'failed': 3}))
        return
    s = optuna.load_study(study_name=name, storage=storage, sampler=optuna.samplers.TPESampler(seed=SEED + 1))
    old = json.loads((out / 'phase1.json').read_text())
    if not len(s.trials) == 9:
        raise RuntimeError('Required validation failed')
    if not [{'number': t.number, 'value': t.value, 'state': t.state.name, 'params': t.params} for t in s.trials] == old:
        raise RuntimeError('Required validation failed')
    s.optimize(objective, n_trials=6, catch=(EvaluationError,))
    trials = s.trials
    failed = [t for t in trials if t.state.name == 'FAIL']
    complete = [t for t in trials if t.state.name == 'COMPLETE']
    if not (len(failed) == 3 and len(complete) == 12 and all((t.value is None for t in failed))):
        raise RuntimeError('Required validation failed')
    best = s.best_trial.user_attrs['measured_config']
    write(out, {'status': 'passed', 'tool': 'optuna', 'version': optuna.__version__, 'seed': SEED, 'resumed_seed': SEED + 1, 'restored_prior_trials': 9, 'total_trials': 15, 'completed': 12, 'failed_without_speed': 3, 'trial_states': [{'number': t.number, 'state': t.state.name, 'objective_seconds': t.value, 'params': t.params} for t in trials], 'best_config': best, 'best_train_seconds': s.best_value, 'replay': b.replay(best)})

def smac_run(out, phase):
    import smac
    from smac import Scenario, HyperparameterOptimizationFacade
    from smac.runhistory.dataclasses import TrialValue
    from ConfigSpace import ConfigurationSpace, Categorical, InCondition, Configuration, ForbiddenAndConjunction, ForbiddenEqualsClause
    cs = ConfigurationSpace(seed=SEED)
    opt = Categorical('opt', [1, 2, 3], default=2)
    tile = Categorical('tile', [4, 8, 16, 32], default=8)
    unroll = Categorical('unroll', [0, 1], default=0)
    vec = Categorical('vectorize', [0, 1], default=1)
    cs.add([opt, tile, unroll, vec])
    cs.add(InCondition(unroll, opt, [2, 3]))
    cs.add(ForbiddenAndConjunction(ForbiddenEqualsClause(tile, 32), ForbiddenEqualsClause(vec, 0)))
    invalid = []
    for c in [{'opt': 1, 'tile': 8, 'unroll': 1, 'vectorize': 1}, {'opt': 2, 'tile': 32, 'unroll': 0, 'vectorize': 0}]:
        try:
            Configuration(cs, values=c)
        except ValueError as e:
            invalid.append({'config': c, 'rejected': True, 'error': str(e)})
        else:
            raise AssertionError('Invalid ConfigSpace candidate accepted')
    b = Benchmark(out, 'smac')
    scenario = Scenario(cs, name='cpg083', output_directory=out / 'smac-state', deterministic=True, n_trials=12, seed=SEED, n_workers=1)

    def target(config, seed: int=SEED):
        return b.evaluate({**DEFAULT, **dict(config)})
    facade = HyperparameterOptimizationFacade(scenario, target_function=target, overwrite=phase == 'start', initial_design=HyperparameterOptimizationFacade.get_initial_design(scenario, n_configs=4))
    prior = facade.runhistory.finished
    if phase == 'start':
        if not prior == 0:
            raise RuntimeError('Required validation failed')
    elif not prior == 6:
        raise RuntimeError(prior)
    for i in range(6):
        info = facade.ask()
        c = clean_config({**DEFAULT, **dict(info.config)})
        v = b.evaluate(c, trial_id={'configuration': c, 'seed': int(info.seed) if info.seed is not None else None})
        facade.tell(info, TrialValue(cost=v, time=v))
    if not facade.runhistory.finished == (6 if phase == 'start' else 12):
        raise RuntimeError('Required validation failed')
    if phase == 'start':
        print(json.dumps({'phase': 'start', 'saved_trials': 6}))
        return
    rows = [json.loads(x) for x in (out / 'evaluations.jsonl').read_text().splitlines() if json.loads(x)['phase'] == 'search']
    best = min(rows, key=lambda r: r['objective_seconds'])
    write(out, {'status': 'passed', 'tool': 'smac', 'version': smac.version, 'seed': SEED, 'configured_budget': 12, 'restored_trials': prior, 'finished_trials': facade.runhistory.finished, 'invalid_configuration_tests': invalid, 'best_config': best['config'], 'best_train_seconds': best['objective_seconds'], 'replay': b.replay(best['config'])})

def opentuner_run(out):
    import random, numpy as np, opentuner
    from opentuner import ConfigurationManipulator, IntegerParameter, EnumParameter, MeasurementInterface, Result
    random.seed(SEED)
    np.random.seed(SEED)
    b = Benchmark(out, 'opentuner')
    selected = {}

    class CPG(MeasurementInterface):

        def manipulator(self):
            m = ConfigurationManipulator()
            m.add_parameter(EnumParameter('mode', ['O1', 'O2', 'O3', 'O2-unroll', 'O3-unroll']))
            m.add_parameter(EnumParameter('tile', [4, 8, 16, 32]))
            m.add_parameter(EnumParameter('vectorize', [0, 1]))
            return m

        @staticmethod
        def decode(c):
            s = c['mode']
            return {'opt': int(s[1]), 'unroll': int('unroll' in s), 'tile': int(c['tile']), 'vectorize': int(c['vectorize'])}

        def run(self, desired_result, input, limit):
            c = self.decode(desired_result.configuration.data)
            self._cpg_attempts = getattr(self, '_cpg_attempts', 0) + 1
            try:
                # Exercise the error path deterministically. The rejected trial
                # remains a failure with no measured speed in evaluations.jsonl.
                v = b.evaluate(c, trial_id=desired_result.id,
                               fault='FAULT_COMPILE' if self._cpg_attempts == 1 else None)
                return Result(time=v)
            except EvaluationError:
                # OpenTuner's MinimizeTime and run_time_limit expect a numeric
                # ordering value. Infinity is a rejection sentinel, never a
                # valid speed sample and never competitive with a finite run.
                return Result(state='ERROR', time=float('inf'))

        def save_final_config(self, configuration):
            selected.update(self.decode(configuration.data))
            self.manipulator().save_to_file(configuration.data, str(out / 'best-configuration.json'))
    parser = opentuner.default_argparser()
    parser.allow_abbrev = False
    args = parser.parse_args(['--test-limit', '16', '--parallelism', '1', '--database', 'sqlite:///' + str(out / 'opentuner.sqlite3'), '--no-dups'])
    CPG.main(args)
    rows = [json.loads(x) for x in (out / 'evaluations.jsonl').read_text().splitlines() if json.loads(x)['phase'] == 'search']
    valid = [row for row in rows if row['status'] == 'ok' and row['valid_speed']]
    rejected = [row for row in rows if not row['valid_speed']]
    if not (len(rows) == 16 and valid and selected and rejected):
        raise RuntimeError('Required validation failed')
    if not any(row['config'] == selected for row in valid):
        raise RuntimeError('Selected configuration has no genuine valid measurement')
    if any(row['objective_seconds'] is not None for row in rejected):
        raise RuntimeError('Rejected trial acquired a fabricated finite performance score')
    write(out, {'status': 'passed', 'tool': 'opentuner', 'seed': SEED,
                'seed_policy': 'Python random and NumPy seeded directly; exact pinned CLI has no --seed option',
                'budget': 16, 'measured_trials': len(rows), 'valid_trials': len(valid), 'rejected_trials': len(rejected),
                'rejection_policy': 'Native ERROR state with positive-infinity ordering sentinel; actual objective_seconds stays null',
                'all_successful_trials_correct': all(row['status'] == 'ok' for row in valid),
                'best_config': selected, 'replay': b.replay(selected), 'correctness_negative_controls': '../negative-controls.json'})
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('tool', choices=['nevergrad', 'optuna', 'smac', 'opentuner'])
    p.add_argument('--out', required=True)
    p.add_argument('--phase', choices=['start', 'resume'], default='start')
    a = p.parse_args()
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if a.tool == 'nevergrad':
        nevergrad_run(out)
    elif a.tool == 'optuna':
        optuna_run(out, a.phase)
    elif a.tool == 'smac':
        smac_run(out, a.phase)
    else:
        opentuner_run(out)
