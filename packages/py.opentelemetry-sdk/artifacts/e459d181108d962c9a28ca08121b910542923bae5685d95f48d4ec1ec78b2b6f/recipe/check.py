#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(sdk_trace, work):
    """Record spans and metric aggregates through real local SDK exporters/readers."""
    trace = installed_module('opentelemetry.trace')
    export = installed_module('opentelemetry.sdk.trace.export')
    memory = installed_module('opentelemetry.sdk.trace.export.in_memory_span_exporter')
    resources = installed_module('opentelemetry.sdk.resources')
    metrics = installed_module('opentelemetry.sdk.metrics')
    metric_export = installed_module('opentelemetry.sdk.metrics.export')
    resource = resources.Resource({'service.name':'cpg-local-check'})
    exporter = memory.InMemorySpanExporter(); provider = sdk_trace.TracerProvider(resource=resource, sampler=installed_module('opentelemetry.sdk.trace.sampling').ALWAYS_ON, shutdown_on_exit=False)
    provider.add_span_processor(export.SimpleSpanProcessor(exporter)); tracer = provider.get_tracer('cpg-check')
    try:
        with tracer.start_as_current_span('parent') as parent:
            parent.set_attribute('resource.id','py.opentelemetry-sdk')
            with tracer.start_as_current_span('child') as child_span:
                child_span.add_event('compiled',{'units':3})
                child_span.record_exception(ValueError('known-fixture-error'))
                child_span.set_status(trace.Status(trace.StatusCode.ERROR,'known-fixture-error'))
        require(provider.force_flush(), 'Span flush failed')
        spans = {span.name:span for span in exporter.get_finished_spans()}
        require(set(spans) == {'parent','child'}, 'Complete span set mismatch')
        require(spans['child'].parent.span_id == spans['parent'].context.span_id and spans['child'].context.trace_id == spans['parent'].context.trace_id, 'Parent/child identity mismatch')
        require(spans['parent'].attributes['resource.id'] == 'py.opentelemetry-sdk', 'Span attribute lost')
        require([event.name for event in spans['child'].events] == ['compiled','exception'] and spans['child'].status.status_code == trace.StatusCode.ERROR, 'Events/error status lost')
    finally: provider.shutdown()
    reader = metric_export.InMemoryMetricReader(); meter_provider = metrics.MeterProvider(resource=resource,metric_readers=[reader],shutdown_on_exit=False)
    try:
        meter = meter_provider.get_meter('cpg-check'); counter = meter.create_counter('runs'); histogram = meter.create_histogram('latency')
        counter.add(2,{'phase':'compile'}); counter.add(3,{'phase':'compile'}); histogram.record(2); histogram.record(5)
        data = reader.get_metrics_data()
        observed = {metric.name:metric for rm in data.resource_metrics for sm in rm.scope_metrics for metric in sm.metrics}
        require(observed['runs'].data.data_points[0].value == 5, 'SDK counter aggregation mismatch')
        point = observed['latency'].data.data_points[0]
        require(point.count == 2 and point.sum == 7 and sum(point.bucket_counts) == 2, 'SDK histogram aggregation mismatch')
        require(data.resource_metrics[0].resource.attributes['service.name'] == 'cpg-local-check', 'Metric resource identity lost')
    finally: meter_provider.shutdown()
    return {'checks':['span-recording-and-flush','complete-span-set','parent-child-identities','attributes','events-and-error-status','counter-aggregation','histogram-aggregation','resource-identity','provider-shutdown'], 'scope':'in-memory trace/metric export; remote OTLP and logging pipeline not exercised'}

if __name__ == "__main__":
    raise SystemExit(main('opentelemetry-sdk', 'opentelemetry.sdk.trace', functional))
