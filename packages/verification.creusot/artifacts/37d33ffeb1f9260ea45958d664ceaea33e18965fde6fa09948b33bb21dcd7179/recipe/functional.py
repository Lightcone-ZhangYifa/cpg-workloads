"""Execute the unchanged Creusot frontend and the fixed, independently logged proof plan."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from runtime_environment import build_environment, runtime_path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def json_stream(raw):
    decoder, result, index = json.JSONDecoder(), [], 0
    while index < len(raw):
        if raw[index].isspace():
            index += 1
            continue
        value, index = decoder.raw_decode(raw, index)
        require(isinstance(value, dict) and 'prover-result' in value and 'term' in value,
                'Unexpected Why3 JSON record')
        result.append(value)
    require(result, 'Why3 emitted no proof result')
    return result


def task_parts(data):
    text = data.decode()
    goals = list(re.finditer(r'^goal\s+([^\s:]+)\s*:', text, re.MULTILINE))
    require(len(goals) == 1, 'Expected one actual exported Why3 task goal')
    match = goals[0]
    end = text.rfind('\nend')
    require(end > match.end(), 'Missing task terminator')
    formula = text[match.end():end].strip()
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[A-Za-z_][\w\']*|\d+|[^\s]', formula)
    return text[:match.start()].encode(), match.group(1), tokens


def main():
    require(len(sys.argv) == 3, 'Usage: functional.py RUNTIME_PAYLOAD PRIVATE_RUN_DIR')
    runtime = Path(sys.argv[1]).resolve()
    config = json.loads((runtime / 'profile-config.json').read_text())
    evidence = Path.cwd() / 'functional-evidence'
    evidence.mkdir(exist_ok=True)
    run_dir = Path(sys.argv[2]).resolve()
    require(run_dir.parent == evidence.resolve() and run_dir.is_dir(), 'Invalid private evidence directory')
    require(os.getpgrp() == os.getpid(), 'The functional runner requires its own process group')
    process_temp = Path(os.environ['CPG_CREUSOT_TMP']).resolve()
    require(process_temp.is_dir() and process_temp.parent == Path('/tmp')
            and process_temp.name.startswith('cpg-creusot-'), 'Missing private process temporary directory')
    environment, selected = build_environment(runtime, config, run_dir, process_temp)
    require(all(os.environ.get(key) == value for key, value in selected.items()),
            'Functional environment differs from the environment checked by the original ELF gate')
    variables = {'runtime': str(runtime), 'run': str(run_dir)}
    prover_config = run_dir / 'why3.conf'
    prover_config.write_text((runtime / 'why3.conf.template').read_text().format_map(variables))
    variables['why3_config'] = str(prover_config)
    why3_base = [str(runtime_path(runtime, 'ocaml-runtime/bin/ocamlrun', directory=False)),
                str(runtime_path(runtime, 'why3-static/bin/why3', directory=False)),
                'prove', '--no-load-default-plugins', '--no-stdlib', '-C', str(prover_config)]
    for relative in config['why3_search_dirs']:
        why3_base.extend(['-L', str(runtime_path(runtime, relative))])
    why3_base.extend(['-F', 'coma'])
    commands, cases = [], []
    summary = {'status': 'running', 'profile': config['profile'],
               'run_relative_path': run_dir.name,
               'source_commit': config['source_commit'],
               'rust_toolchain': config['rust_toolchain'],
               'why3_engine': config['why3_engine'], 'why3_logic_library': config['why3_logic_library'],
               'configured_provers': config['provers'],
               'upstream_frontend_flags': config['upstream_frontend_flags'],
               'cases': cases}
    write_json(run_dir / 'result.json', summary)

    def execute(label, argv, cwd, timeout):
        start = time.monotonic()
        stdout, stderr = run_dir / (label + '.stdout.log'), run_dir / (label + '.stderr.log')
        command = {'label': label, 'argv': argv, 'cwd': str(cwd),
                   'stdout': stdout.name, 'stderr': stderr.name}
        try:
            with stdout.open('w') as out, stderr.open('w') as err:
                process = subprocess.run(argv, cwd=cwd, env=environment, stdout=out,
                                         stderr=err, timeout=timeout)
            command.update(returncode=process.returncode, timed_out=False)
        except subprocess.TimeoutExpired:
            command.update(returncode=None, timed_out=True)
            raise
        finally:
            command['seconds'] = time.monotonic() - start
            for field, path in (('stdout', stdout), ('stderr', stderr)):
                if path.exists():
                    command[field + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            commands.append(command)
            write_json(run_dir / 'commands.json', commands)
        return process.returncode, stdout.read_text(), stderr.read_text()

    def why3_query(coma, fixture, goals, prover, transformations=(), seconds=30):
        require(prover in config['provers'], 'Undeclared fixed prover')
        argv = why3_base + ['-P', prover, '-t', str(seconds), '-m', '512', '--json']
        for transformation in transformations:
            argv.extend(['-a', transformation])
        argv.extend([str(coma), '-T', fixture['expected_theory']])
        for goal in goals:
            argv.extend(['-G', goal])
        return argv

    def checked_records(raw, goals):
        records = json_stream(raw)
        names = [item['term']['goal_name'] for item in records]
        require(len(names) == len(set(names)) and set(names) == set(goals),
                'Why3 omitted, duplicated, or substituted a declared goal')
        return records

    def native_witness(text, case, label):
        # Append a harness to the entire same annotated source; no body projection or rewriting.
        harness = '\nfn main() {\n    let actual = unused_in_loop(true);\n'
        harness += '    println!("CPG_WITNESS b=true actual={} good_post={} bad_post={}", actual, actual == 10, actual == 11);\n'
        harness += '    if actual != 10 || actual == 11 { std::process::exit(21); }\n}\n'
        witness_source = case / 'native_witness.rs'
        witness_source.write_text(text + harness)
        executable = case / 'native_witness'
        local = {**variables, 'native_input': str(witness_source), 'native_exe': str(executable)}
        argv = [item.format_map(local) for item in config['native_rustc_argv']]
        require(Path(argv[0]).resolve() == runtime_path(runtime, config['native_rustup'], directory=False)
                and argv[1:4] == ['run', config['rust_toolchain'], 'rustc'],
                'Native witness must use real private rustup and the exact paired original rustc')
        native_compiler = runtime_path(runtime, config['native_rustc'], directory=False)
        require(argv.count(str(witness_source)) == 1 and argv.count('-o') == 1
                and argv.index('-o') + 1 < len(argv) and argv[argv.index('-o') + 1] == str(executable),
                'Native compiler command is not bound to this exact source and output')
        require(not executable.exists() and witness_source.read_bytes() == (text + harness).encode(),
                'Native witness must start with the exact full annotated source and no old executable')
        rc, out, err = execute(label + '-native-build', argv, case, 180)
        require(rc == 0 and executable.is_file(), 'Same-source native witness did not compile')
        require(witness_source.read_bytes() == (text + harness).encode(),
                'Native compilation changed the exact witness source')
        rc, out, err = execute(label + '-native-run', [str(executable)], case, 20)
        require(rc == 0 and out == 'CPG_WITNESS b=true actual=10 good_post=true bad_post=false\n',
                'Actual native witness does not confirm the expected source behavior')
        value = {'status': 'passed', 'input_b': True, 'actual': 10,
                 'good_postcondition_holds': True, 'bad_postcondition_holds': False,
                 'full_original_annotated_source_preserved_as_prefix': witness_source.read_text().startswith(text),
                 'verified_source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                 'appended_harness_sha256': hashlib.sha256(harness.encode()).hexdigest(),
                 'compiled_source_sha256': hashlib.sha256(witness_source.read_bytes()).hexdigest(),
                 'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                 'compiler': str(native_compiler), 'launcher': argv[:4],
                 'scope': 'Actual terminating b=true execution; no claim that b=false terminates'}
        write_json(case / 'native-witness.json', value)
        return value

    def exported_task(coma, fixture, case, label, negated):
        directory = case / ('negated-task' if negated else 'original-task')
        directory.mkdir()
        argv = list(why3_base)
        if negated:
            argv.extend(['-a', 'smoke_detector_top'])
        argv.extend([str(coma), '-T', fixture['expected_theory'], '-G', fixture['negative_goal'],
                     '-D', 'why3', '-o', str(directory)])
        rc, out, err = execute(label + '-export-' + ('negated' if negated else 'original'), argv, case, 120)
        files = [file for file in directory.iterdir() if file.is_file()]
        require(rc == 0 and len(files) == 1, 'Expected one actual Why3 task export')
        return files[0]

    def counterproof(coma, fixture, case, label):
        # This is a separate claim: Gamma entails NOT(original VC), never a positive proof-plan step.
        original = exported_task(coma, fixture, case, label, False)
        negative = exported_task(coma, fixture, case, label, True)
        context1, name1, tokens1 = task_parts(original.read_bytes())
        context2, name2, tokens2 = task_parts(negative.read_bytes())
        require(context1 == context2 and name1 == name2 and tokens2 == ['not', '('] + tokens1 + [')'],
                'Counterproof changed the background or is not the exact whole-VC negation')
        exact = {'status': 'passed', 'context_identical_byte_for_byte': True,
                 'context_sha256': hashlib.sha256(context1).hexdigest(),
                 'goal_name_identical': True, 'negated_goal_tokens_are_exactly_not_original': True,
                 'original_task_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
                 'negated_task_sha256': hashlib.sha256(negative.read_bytes()).hexdigest(),
                 'transformation': 'smoke_detector_top only, applied to the original full VC'}
        write_json(case / 'exact-negation-check.json', exact)
        argv = why3_query(coma, fixture, [fixture['negative_goal']], 'CVC5', ['smoke_detector_top'])
        rc, out, err = execute(label + '-negative-counterproof', argv, case, 120)
        records = checked_records(out, [fixture['negative_goal']])
        require(rc == 0 and all(item['prover-result']['answer'] == 'Valid'
                               and item['prover-result']['status'] == 'exited with status 0'
                               for item in records), 'The exact negative VC was not proved')
        value = {'status': 'passed', 'polarity': 'negated_original_goal',
                 'original_bad_goal_proved': False, 'answer': 'Valid',
                 'scope': 'Proof of NOT(original bad VC), relative to the unchanged standard context; not an original-VC Valid result',
                 'exact_task_binding': exact, 'raw_results': records}
        write_json(case / 'negative-counterproof.json', value)
        return value

    def good_negation_control(coma, fixture, case, label):
        argv = why3_query(coma, fixture, [fixture['negative_goal']], 'CVC5', ['smoke_detector_top'], seconds=5)
        rc, out, err = execute(label + '-good-negation-control', argv, case, 45)
        records = checked_records(out, [fixture['negative_goal']])
        contradiction = any(item['prover-result']['answer'] == 'Valid' for item in records)
        require(not contradiction, 'Both the good VC and its exact negation were proved')
        value = {'contradiction_detected': False, 'proves_background_consistency': False,
                 'scope': 'No contradictory proof observed; Unknown/limits do not prove context consistency',
                 'returncode': rc, 'polarity': 'negated_good_goal', 'raw_results': records}
        write_json(case / 'good-negation-control.json', value)
        return value

    try:
        host_cc = shutil.which('cc', path=environment['PATH'])
        require(host_cc is not None, 'The declared host C linker driver is missing')
        rc, cc_version, cc_error = execute('host-cc-version', [host_cc, '--version'], run_dir, 20)
        require(rc == 0, 'The declared host C linker driver does not execute')
        rc, cc_target, cc_error = execute('host-cc-target', [host_cc, '-dumpmachine'], run_dir, 20)
        require(rc == 0 and cc_target.strip().startswith('x86_64'), 'Unexpected host C linker target')
        summary['host_linker'] = {'driver': host_cc, 'resolved_driver': str(Path(host_cc).resolve()),
                                  'sha256': hashlib.sha256(Path(host_cc).read_bytes()).hexdigest(),
                                  'version': cc_version.splitlines()[0], 'target': cc_target.strip(),
                                  'scope': 'Host C linker and CRT are declared dependencies; actual native linking is required below'}
        fixtures = config['fixtures']
        require({item['name'] for item in fixtures} == {'sum', 'unused_in_loop'} and len(fixtures) == 2,
                'The two declared official loop fixtures are required')
        for fixture in fixtures:
            source_path = runtime_path(runtime, 'fixtures/' + fixture['filename'], directory=False)
            source = source_path.read_text()
            require(hashlib.sha256(source.encode()).hexdigest() == fixture['official_fixture_sha256'],
                    'Official Rust fixture differs from the fixed source')
            planned = [goal for part in fixture['proof_plan'] for goal in part['goals']]
            require(len(planned) == len(set(planned)) and set(planned) == set(fixture['expected_goals']),
                    'The positive proof plan must cover every original goal exactly once')
            variants = [('good', source)]
            if fixture['name'] == 'unused_in_loop':
                old, new = '#[ensures(result == 10u32)]', '#[ensures(result == 11u32)]'
                require(source.count(old) == 1 and planned == [fixture['negative_goal']],
                        'The official negative mutation and single full VC must be exact')
                variants.append(('bad_postcondition', source.replace(old, new)))
            for kind, text in variants:
                label = fixture['name'] + '-' + kind
                case = run_dir / label
                case.mkdir()
                rust = case / fixture['filename']
                rust.write_text(text)
                local = {**variables, 'case': str(case), 'input': str(rust), 'crate': fixture['name']}
                frontend = [value.format_map(local) for value in config['frontend_argv']]
                rc, stdout, stderr = execute(label + '-frontend', frontend, case, 240)
                require(rc == 0, 'Rust frontend failed; this is not a semantic negative result')
                coma = case / (fixture['name'] + '.coma')
                coma.write_text(stdout)
                require('module ' + fixture['expected_theory'] in stdout, 'Missing actual generated Coma module')
                generated_goals = {'vc_' + name for name in re.findall(r"^  let rec ([A-Za-z_][A-Za-z0-9_']*)", stdout, re.M)}
                require(generated_goals == set(fixture['expected_goals']),
                        'Generated functions differ from the complete fixed proof plan')
                inventory_rc, inventory_text, inventory_stderr = execute(
                    label + '-goal-inventory', why3_base + ['--print-theory', str(coma)], case, 120)
                require(inventory_rc == 0, 'Unfiltered Why3 goal inventory failed')
                inventory, theory = [], None
                for line in inventory_text.splitlines():
                    match = re.match(r'^theory (\S+)', line)
                    if match:
                        theory = match.group(1)
                    match = re.match(r'^\s+goal (\S+)\s*:', line)
                    if match:
                        require(theory is not None, 'A Why3 goal has no enclosing theory')
                        inventory.append((theory, match.group(1)))
                expected = {(fixture['expected_theory'], goal) for goal in fixture['expected_goals']}
                require(len(inventory) == len(set(inventory)) and set(inventory) == expected,
                        'Unfiltered complete Why3 goal inventory differs from the proof plan')
                write_json(case / 'goal-inventory.json',
                           {'scope': 'Original unfiltered --print-theory; never evidence of a transformed goal',
                            'goals': [{'theory': name, 'goal': goal} for name, goal in inventory],
                            'stdout_sha256': hashlib.sha256(inventory_text.encode()).hexdigest()})
                result = {'fixture': fixture['name'], 'case': kind,
                          'rust_sha256': hashlib.sha256(text.encode()).hexdigest(),
                          'coma_sha256': hashlib.sha256(stdout.encode()).hexdigest(),
                          'frontend_returncode': rc, 'original_goal_results': []}
                cases.append(result)
                for part in fixture['proof_plan']:
                    require(all(item == 'compute_specified' for item in part.get('transformations', [])),
                            'Only the declared positive proof normalization is allowed here; never goal negation')
                    argv = why3_query(coma, fixture, part['goals'], part['prover'], part.get('transformations', []))
                    rc, out, err = execute(label + '-' + part['name'], argv, case, 180)
                    records = checked_records(out, part['goals'])
                    for record in records:
                        answer = record['prover-result']['answer']
                        require(record['prover-result']['status'] == 'exited with status 0',
                                'A solver signal, OOM or process failure is not a semantic negative')
                        if kind == 'good':
                            require(rc == 0 and answer == 'Valid', 'A complete positive goal did not pass')
                        else:
                            normalized = ' '.join(answer.split())
                            require(rc == 2 and normalized == 'Unknown (unknown + incomplete)',
                                    'Expected the actual ordinary incomplete result; it is not itself a qualification')
                        result['original_goal_results'].append({'polarity': 'original', 'name': record['term']['goal_name'],
                                                                'answer': answer, 'prover': part['prover'], 'raw_result': record})
                require({item['name'] for item in result['original_goal_results']} == set(fixture['expected_goals']),
                        'Incomplete original-goal coverage')
                if fixture['name'] == 'unused_in_loop':
                    result['native_witness'] = native_witness(text, case, label)
                    if kind == 'good':
                        result['good_negation_control'] = good_negation_control(coma, fixture, case, label)
                    else:
                        result['negative_counterproof'] = counterproof(coma, fixture, case, label)
                        result['ordinary_unknown_is_not_a_pass'] = True
                result['status'] = 'proved' if kind == 'good' else 'false_post_refuted_and_native_witness_confirmed'
                write_json(case / 'proof-results.json', result)
        summary['status'] = 'passed'
        write_json(run_dir / 'result.json', summary)
        print(json.dumps(summary, ensure_ascii=False))
    except BaseException as error:
        summary.update(status='failed', error=repr(error))
        write_json(run_dir / 'result.json', summary)
        raise


if __name__ == '__main__':
    main()
