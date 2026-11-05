#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(tb, work):
    """Write real event files and decode their framed protobuf scalar records."""
    import struct
    event_pb2 = installed_module('tensorboardX.proto.event_pb2')
    crc32c = installed_module('tensorboardX.crc32c')
    require(crc32c.crc32c(b'123456789') == 0xe3069283, 'CRC32C published check vector mismatch')
    def masked_crc(raw):
        value = crc32c.crc32c(raw)
        return (((value >> 15) | (value << 17)) + 0xa282ead8) & 0xffffffff
    directory = work / 'events'
    writer = tb.SummaryWriter(logdir=str(directory), max_queue=1, flush_secs=1)
    try:
        for step,value in [(0,1.5),(1,2.5),(2,4.0)]: writer.add_scalar('compile/loss',value,step,walltime=1700000000+step)
        writer.add_text('run/note','compiler check',global_step=2,walltime=1700000002)
        writer.flush()
    finally: writer.close()
    paths = sorted(directory.glob('events.out.tfevents.*'))
    require(len(paths) == 1, 'Expected one real event file')
    raw = paths[0].read_bytes(); offset = 0; events = []
    while offset < len(raw):
        require(len(raw)-offset >= 16, 'Truncated record frame')
        length_bytes = raw[offset:offset+8]; length = struct.unpack('<Q',length_bytes)[0]
        header_crc = struct.unpack('<I',raw[offset+8:offset+12])[0]
        payload = raw[offset+12:offset+12+length]
        require(len(payload) == length and offset+16+length <= len(raw), 'Truncated record payload')
        payload_crc = struct.unpack('<I',raw[offset+12+length:offset+16+length])[0]
        require(masked_crc(length_bytes) == header_crc and masked_crc(payload) == payload_crc, 'Event CRC mismatch')
        events.append(event_pb2.Event.FromString(payload)); offset += 16 + length
    scalars = [(event.step, value.simple_value) for event in events for value in event.summary.value if value.tag == 'compile/loss']
    require(scalars == [(0,1.5),(1,2.5),(2,4.0)], 'Event scalar/step values mismatch')
    require(any(value.tag == 'run/note/text_summary' for event in events for value in event.summary.value), 'Text event missing')
    require(any(event.file_version.startswith('brain.Event:') for event in events), 'Event stream header missing')
    bad_writer = tb.SummaryWriter(logdir=str(work/'bad'))
    try: raises((AssertionError,TypeError,ValueError), lambda: bad_writer.add_scalar('bad',[1,2],0), 'Nonscalar input accepted')
    finally: bad_writer.close()
    return {'checks':['real-event-file','complete-frame-consumption','crc32c-known-vector','length-and-payload-crc32c','scalar-step-values','text-event','stream-version','nonscalar-rejection','flush-and-close'], 'events':len(events), 'scope':'local scalar/text logging and framed protobuf files; no remote dashboards or graph backends'}

if __name__ == "__main__":
    raise SystemExit(main('tensorboardx', 'tensorboardX', functional))
