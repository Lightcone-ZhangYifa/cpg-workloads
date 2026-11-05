#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pc, work):
    """Check metric values, labels, histogram buckets and text exposition."""
    parser = installed_module('prometheus_client.parser')
    registry = pc.CollectorRegistry()
    counter = pc.Counter('cpg_runs', 'Executed runs', ['phase'], registry=registry)
    counter.labels(phase='compile').inc(2); counter.labels(phase='compile').inc(3)
    gauge = pc.Gauge('cpg_active', 'Active jobs', registry=registry); gauge.set(3); gauge.dec(); gauge.inc(2)
    histogram = pc.Histogram('cpg_time', 'Time samples', buckets=[1,5], registry=registry)
    for value in [1,3,6]: histogram.observe(value)
    raw = pc.generate_latest(registry)
    families = list(parser.text_string_to_metric_families(raw.decode()))
    samples = {(sample.name, tuple(sorted(sample.labels.items()))): sample.value for family in families for sample in family.samples}
    require(samples[('cpg_runs_total',(('phase','compile'),))] == 5, 'Counter aggregation failed')
    require(samples[('cpg_active',())] == 4, 'Gauge mutation failed')
    require(samples[('cpg_time_count',())] == 3 and samples[('cpg_time_sum',())] == 10, 'Histogram total/count mismatch')
    buckets = {labels[0][1]:value for (name,labels),value in samples.items() if name == 'cpg_time_bucket'}
    require(buckets == {'1.0':1,'5.0':2,'+Inf':3}, 'Cumulative histogram buckets mismatch')
    require(b'# HELP cpg_runs_total' in raw and b'# TYPE cpg_time histogram' in raw, 'Exposition metadata missing')
    raises(ValueError, lambda: counter.labels('compile').inc(-1), 'Negative counter increment accepted')
    raises(ValueError, lambda: counter.labels(unexpected='compile'), 'Wrong label set accepted')
    raises(ValueError, lambda: pc.Gauge('cpg_active','duplicate',registry=registry), 'Duplicate registration accepted')
    return {'checks': ['counter-aggregation', 'gauge-updates', 'histogram-count-sum-buckets', 'text-exposition-parse', 'help-and-type', 'negative-counter', 'wrong-labels', 'duplicate-registration'], 'scope': 'in-process registry and exposition; no HTTP listener or multiprocess collector qualification'}

if __name__ == "__main__":
    raise SystemExit(main('prometheus-client', 'prometheus_client', functional))
