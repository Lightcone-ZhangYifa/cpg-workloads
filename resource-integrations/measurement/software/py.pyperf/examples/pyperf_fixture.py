"""Invoke only in the existing, pinned py.pyperf environment; no install step."""
import pyperf

values = tuple(range(1024))
expected = 1024 * 1023 // 2
if sum(values) != expected:
    raise SystemExit("preflight failed")


def work():
    result = sum(values)
    if result != expected:
        raise RuntimeError("checksum changed")
    return result


runner = pyperf.Runner()
runner.metadata["cpg_resource_id"] = "py.pyperf"
runner.metadata["correctness"] = "sum(0..1023) == 523776"
runner.bench_func("sum_1024", work)
