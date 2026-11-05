#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(protobuf, work):
    """Check dynamic message descriptors, binary/JSON codecs and field failures."""
    descriptors = installed_module('google.protobuf.descriptor_pb2')
    pools = installed_module('google.protobuf.descriptor_pool')
    factories = installed_module('google.protobuf.message_factory')
    json_format = installed_module('google.protobuf.json_format')
    message_api = installed_module('google.protobuf.message')
    document = descriptors.FileDescriptorProto(name='cpg.proto', package='cpg', syntax='proto3')
    message = document.message_type.add(name='Result')
    message.field.add(name='run_id', number=1, label=1, type=3)
    message.field.add(name='values', number=2, label=3, type=1)
    message.field.add(name='label', number=3, label=1, type=9)
    pool = pools.DescriptorPool(); pool.Add(document)
    Result = factories.GetMessageClass(pool.FindMessageTypeByName('cpg.Result'))
    record = Result(run_id=7, values=[1.5,2.0], label='compiler')
    raw = record.SerializeToString(deterministic=True); decoded = Result.FromString(raw)
    require(decoded == record and raw.startswith(bytes([8,7])), 'Binary message round trip/wire field failed')
    data = json_format.MessageToDict(record, preserving_proto_field_name=True)
    require(data == {'run_id':'7','values':[1.5,2.0],'label':'compiler'}, 'Protobuf JSON representation mismatch')
    require(json_format.ParseDict(data, Result()) == record, 'JSON parse failed')
    clone = Result(); clone.CopyFrom(record); clone.values.append(3.0)
    require(list(record.values) == [1.5,2.0] and len(clone.values) == 3, 'Message copy was not independent')
    raises(TypeError, lambda: setattr(record,'run_id','bad'), 'Wrong integer field type accepted')
    raises(TypeError, lambda: record.values.append('bad'), 'Wrong repeated field type accepted')
    raises(message_api.DecodeError, lambda: Result.FromString(bytes([128])), 'Truncated varint accepted')
    raises(json_format.ParseError, lambda: json_format.ParseDict({'unknown':1}, Result()), 'Unknown JSON field accepted')
    return {'checks': ['descriptor-pool-and-dynamic-class', 'deterministic-binary-roundtrip', 'known-wire-field', 'json-field-contract', 'independent-copy', 'scalar-type', 'repeated-type', 'truncated-wire', 'unknown-json-field']}

if __name__ == "__main__":
    raise SystemExit(main('protobuf', 'google.protobuf', functional))
