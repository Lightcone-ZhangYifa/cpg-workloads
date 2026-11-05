#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(trace, work):
    """Check trace context scope, W3C propagation, baggage and invalid headers."""
    context_api = installed_module('opentelemetry.context')
    baggage = installed_module('opentelemetry.baggage')
    propagation = installed_module('opentelemetry.trace.propagation.tracecontext')
    baggage_propagation = installed_module('opentelemetry.baggage.propagation')
    span_context = trace.SpanContext(trace_id=0x1234, span_id=0x5678, is_remote=False, trace_flags=trace.TraceFlags.SAMPLED)
    span = trace.NonRecordingSpan(span_context)
    selected = trace.set_span_in_context(span)
    previous = trace.get_current_span()
    token = context_api.attach(selected)
    try: require(trace.get_current_span().get_span_context() == span_context, 'Attached span context lost')
    finally: context_api.detach(token)
    require(trace.get_current_span() is previous, 'Context detach did not restore previous state')
    propagator = propagation.TraceContextTextMapPropagator(); carrier = {}
    propagator.inject(carrier, context=selected)
    require(carrier['traceparent'] == '00-00000000000000000000000000001234-0000000000005678-01', 'W3C traceparent encoding mismatch')
    restored = trace.get_current_span(propagator.extract(carrier)).get_span_context()
    require(restored.trace_id == span_context.trace_id and restored.span_id == span_context.span_id and restored.is_remote, 'W3C extraction mismatch')
    invalid = trace.get_current_span(propagator.extract({'traceparent':'invalid'})).get_span_context()
    require(not invalid.is_valid, 'Invalid traceparent accepted')
    bag_context = baggage.set_baggage('workflow','compile test',context=selected)
    bag_prop = baggage_propagation.W3CBaggagePropagator(); bag_carrier = {}; bag_prop.inject(bag_carrier,context=bag_context)
    require(baggage.get_baggage('workflow',context=bag_prop.extract(bag_carrier)) == 'compile test', 'Baggage propagation failed')
    require(baggage.get_baggage('workflow',context=baggage.remove_baggage('workflow',context=bag_context)) is None, 'Baggage removal failed')
    return {'checks': ['explicit-span-context', 'attach-detach-restoration', 'w3c-traceparent-encoding', 'remote-context-extraction', 'invalid-traceparent', 'baggage-roundtrip', 'baggage-removal'], 'scope':'public API context and propagation; recording/export requires a separate SDK'}

if __name__ == "__main__":
    raise SystemExit(main('opentelemetry-api', 'opentelemetry.trace', functional))
