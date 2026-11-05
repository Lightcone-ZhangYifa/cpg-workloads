#!/usr/bin/env python3
"""Exercise every compiled sequential RAJAPerf kernel with its own tolerances."""
import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from native_inventory import inventory, sha, execution_matrix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    evidence = prefix / 'share/compiler-playground/rajaperf'
    profile = json.loads((evidence / 'profile.json').read_text())
    expected = json.loads((evidence / 'material-manifest.json').read_text())['files']
    assert inventory(prefix / 'share/rajaperf/source') == expected
    executable = prefix / 'bin/raja-perf.exe'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LD_', 'GTEST_', 'GMOCK_')) and k != 'RAJA_PERFSUITE_UNIT_TEST'}
    env.update(LC_ALL='C', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    runtime = subprocess.run(['ldd', str(executable)], capture_output=True, text=True, env=env, check=False)
    assert runtime.returncode == 0 and 'not found' not in runtime.stdout + runtime.stderr
    assert '/state/operations/' not in runtime.stdout and 'private-build-tools' not in runtime.stdout
    with tempfile.TemporaryDirectory(prefix='cpg-rajaperf-native-check-') as temporary:
        temporary = Path(temporary)
        argv = [str(executable), '--checkrun', str(profile['runtime_probe_repetitions']),
                '--size', str(profile['runtime_probe_problem_size']), '--warmup-disable',
                '--outdir', str(temporary), '--outfile', 'native', '--show-progress']
        result = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=temporary,
                                check=False, timeout=240)
        print(json.dumps({'scope': 'original_native_run_outputs_before_checker_assertions',
              'argv': argv, 'returncode': result.returncode, 'stdout': result.stdout,
              'stderr': result.stderr,
              'csv': (temporary / 'native-kernel-run-data.csv').read_text() if (temporary / 'native-kernel-run-data.csv').exists() else None,
              'checksum_report': (temporary / 'native-checksum.txt').read_text() if (temporary / 'native-checksum.txt').exists() else None}, sort_keys=True), flush=True)
        assert result.returncode == 0 and 'FAILED checksum' not in result.stdout
        assert 'Bad input' not in result.stdout + result.stderr
        csv_text = (temporary / 'native-kernel-run-data.csv').read_text()
        raw_rows = list(csv.reader(io.StringIO(csv_text)))
        assert raw_rows and raw_rows.pop(0) == ['Kernels run without MPI']
        assert raw_rows and [s.strip() for s in raw_rows[0]][:5] == ['Kernel', 'Variant', 'Tuning', 'Problem size', 'Checksum']
        rows = [[cell.strip() for cell in row] for row in raw_rows[1:] if row]
        assert rows and all(len(row) == 8 and row[4] == 'PASSED' for row in rows)
        combinations = [row[:3] for row in rows]
        assert len({tuple(row) for row in combinations}) == len(combinations), 'Duplicate kernel/variant/tuning CSV row'
        actual_matrix = execution_matrix(result.stdout)
        assert actual_matrix == profile['upstream_executed_matrix'], 'Native supported/executed matrix differs from the complete original upstream test'
        assert sorted(combinations) == actual_matrix['executed']
        assert sorted({row[0] for row in rows}) == profile['kernels']
        assert sorted({row[1] for row in rows}) == sorted(profile['variants'])
        assert all(math.isfinite(float(row[5])) and float(row[5]) > 0 for row in rows)
        checksum_text = (temporary / 'native-checksum.txt').read_text()
        checksums = []
        for line in checksum_text.splitlines():
            if re.match(r'^(Base_Seq|Lambda_Seq|RAJA_Seq)-', line):
                cells = line.split()
                assert len(cells) == 5 and cells[1] == 'PASSED'
                tolerance, checksum, difference = map(float, cells[2:])
                assert all(math.isfinite(v) for v in (tolerance, checksum, difference))
                assert 0 <= difference <= tolerance
                checksums.append({'variant_tuning': cells[0], 'tolerance': tolerance,
                                  'checksum': checksum, 'relative_absolute_difference': difference})
        assert len(checksums) == len(rows)
        print(json.dumps({'status': 'passed', 'resource_id': 'rajaperf',
              'executable_sha256': sha(executable), 'kernel_count': len(profile['kernels']),
              'variant_tuning_rows': len(rows), 'all_original_tolerances_satisfied': True,
              'complete_exact_execution_matrix': actual_matrix,
              'problem_size_request': profile['runtime_probe_problem_size'],
              'repetitions': profile['runtime_probe_repetitions'], 'argv': argv,
              'ldd': runtime.stdout, 'stdout': result.stdout, 'stderr': result.stderr,
              'kernel_run_data_csv': csv_text, 'checksum_report': checksum_text,
              'official_performance_score': False, 'unperformed': profile['unperformed']}, sort_keys=True))


if __name__ == '__main__':
    main()
