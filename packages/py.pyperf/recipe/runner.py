#!/usr/bin/env python3
"""A small correct workload executed through pyperf's official Runner."""
import pyperf


def reduction():
    value = sum(number * number for number in range(10000))
    if value != 333283335000:
        raise ValueError("The benchmark workload produced an incorrect value")
    return value


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_func("cpg-integer-reduction", reduction)
