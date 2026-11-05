"""Bounded local TensorBoard HTTP/2 + gRPC probe with explicit status checks.

Only Python's standard library is used. RFC 7541 Appendix A/B tables are
generated from the retained normative RFC; there is no hpack/grpcio dependency.
The HTTP/2 state machine accepts one response stream per fresh connection,
bounded HPACK headers and identity-encoded unary Protobuf messages. Unsupported
compression, malformed framing, missing trailers and unexpected statuses fail.
This is a qualification fixture, not a general-purpose network client.

Protocol sources: RFC 9113; RFC 7541; grpc/grpc doc/PROTOCOL-HTTP2.md;
tensorflow/tensorboard tensorboard/data/proto/data_provider.proto.
"""
from pathlib import Path
import hashlib
import re
import socket
import struct
import subprocess
import time
from urllib.parse import unquote

MAX_FRAME_BYTES = 16384
MAX_HEADER_BYTES = 8192
MAX_BODY_BYTES = 65535
MAX_FRAMES = 128
RPC_SECONDS = 5.0


class ProtocolError(ValueError):
    """A bounded protocol assertion failed; never converted into a pass."""


def expect(condition, reason):
    if not condition:
        raise ProtocolError(reason)


def varint(number):
    expect(isinstance(number, int) and 0 <= number < 2**64, 'Invalid protobuf integer')
    value = bytearray()
    while number >= 128:
        value.append((number & 127) | 128)
        number >>= 7
    value.append(number)
    return bytes(value)


def field(number, payload):
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def crc32c(data):
    crc = 0xffffffff
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    return (~crc) & 0xffffffff


def masked(data):
    crc = crc32c(data)
    return (((crc >> 15) | (crc << 17)) + 0xa282ead8) & 0xffffffff


def record(data):
    length = struct.pack('<Q', len(data))
    return length + struct.pack('<I', masked(length)) + data + struct.pack('<I', masked(data))


def event_bytes():
    header = varint(9) + struct.pack('<d', 1761850000.0) + varint(16) + varint(0) + field(3, b'brain.Event:2')
    scalar = field(1, b'loss/step') + varint(21) + struct.pack('<f', 1.25)
    event = varint(9) + struct.pack('<d', 1761850001.0) + varint(16) + varint(17) + field(5, field(1, scalar))
    data = record(header) + record(event)
    expect(hashlib.sha256(data).hexdigest() == '5bf8a8a4250f7c5b7be0546e4b79aee551b40b30799c7a1f39c361a94703f0dc', 'Event fixture identity changed')
    return data


def frame(kind, flags, stream, data=b''):
    expect(0 <= len(data) <= MAX_FRAME_BYTES and 0 <= stream < 2**31, 'Invalid outgoing frame')
    return len(data).to_bytes(3, 'big') + bytes([kind, flags]) + struct.pack('>I', stream) + data


def hpack_string(value):
    data = value.encode('ascii')
    expect(len(data) < 127, 'Fixed request header unexpectedly long')
    return bytes([len(data)]) + data


def hpack_integer(data, offset, bits):
    expect(offset < len(data), 'Truncated HPACK integer')
    mask = (1 << bits) - 1
    value = data[offset] & mask
    offset += 1
    if value < mask:
        return value, offset
    shift = 0
    while True:
        expect(offset < len(data) and shift <= 28, 'Truncated or excessive HPACK integer')
        byte = data[offset]
        offset += 1
        value += (byte & 127) << shift
        expect(value <= 0x7fffffff, 'HPACK integer exceeds bounded range')
        if not byte & 128:
            return value, offset
        shift += 7


_HUFFMAN_TREE = None


def huffman_decode(data):
    global _HUFFMAN_TREE
    if _HUFFMAN_TREE is None:
        tree = {}
        for symbol, (code, length) in enumerate(_HUFFMAN_CODES):
            node = tree
            for shift in range(length - 1, -1, -1):
                node = node.setdefault((code >> shift) & 1, {})
            expect('symbol' not in node and not node, 'Invalid protocol Huffman table')
            node['symbol'] = symbol
        _HUFFMAN_TREE = tree
    node = _HUFFMAN_TREE
    result = bytearray()
    tail_value = tail_bits = 0
    for byte in data:
        for shift in range(7, -1, -1):
            bit = (byte >> shift) & 1
            expect(bit in node, 'Invalid HPACK Huffman prefix')
            node = node[bit]
            tail_value = (tail_value << 1) | bit
            tail_bits += 1
            if 'symbol' in node:
                symbol = node['symbol']
                expect(symbol != 256, 'HPACK Huffman EOS symbol is forbidden')
                result.append(symbol)
                expect(len(result) <= MAX_HEADER_BYTES, 'Decoded HPACK string exceeds budget')
                node = _HUFFMAN_TREE
                tail_value = tail_bits = 0
    expect(tail_bits <= 7 and tail_value == (1 << tail_bits) - 1, 'Invalid HPACK Huffman padding')
    return bytes(result)


def hpack_literal(data, offset):
    expect(offset < len(data), 'Truncated HPACK string')
    huffman = bool(data[offset] & 128)
    length, offset = hpack_integer(data, offset, 7)
    expect(length <= MAX_HEADER_BYTES and offset + length <= len(data), 'Truncated or excessive HPACK string')
    value = data[offset:offset + length]
    return (huffman_decode(value) if huffman else value), offset + length


class HpackDecoder:
    """Full RFC 7541 representations with a bounded per-connection table."""
    def __init__(self, maximum_table_size=4096):
        expect(0 <= maximum_table_size <= 4096, 'Excessive HPACK table setting')
        self.maximum = maximum_table_size
        self.limit = maximum_table_size
        self.dynamic = []
        self.size = 0

    def lookup(self, index):
        expect(1 <= index <= len(_STATIC) + len(self.dynamic), 'Invalid HPACK table index')
        return _STATIC[index - 1] if index <= len(_STATIC) else self.dynamic[index - len(_STATIC) - 1]

    def evict(self):
        while self.size > self.limit:
            name, value = self.dynamic.pop()
            self.size -= len(name) + len(value) + 32

    def decode(self, data):
        expect(len(data) <= MAX_HEADER_BYTES, 'Compressed HPACK header block exceeds budget')
        headers = []
        offset = total = 0
        while offset < len(data):
            byte = data[offset]
            if byte & 128:
                index, offset = hpack_integer(data, offset, 7)
                name, value = self.lookup(index)
            elif byte & 64:
                index, offset = hpack_integer(data, offset, 6)
                if index:
                    name = self.lookup(index)[0]
                else:
                    name, offset = hpack_literal(data, offset)
                value, offset = hpack_literal(data, offset)
                self.dynamic.insert(0, (name, value))
                self.size += len(name) + len(value) + 32
                self.evict()
            elif byte & 32:
                expect(not headers, 'HPACK table size update after a header field')
                size, offset = hpack_integer(data, offset, 5)
                expect(size <= self.maximum, 'HPACK table exceeds advertised maximum')
                self.limit = size
                self.evict()
                continue
            else:  # Literal without indexing and literal never indexed.
                index, offset = hpack_integer(data, offset, 4)
                if index:
                    name = self.lookup(index)[0]
                else:
                    name, offset = hpack_literal(data, offset)
                value, offset = hpack_literal(data, offset)
            total += len(name) + len(value) + 32
            expect(total <= MAX_HEADER_BYTES and len(headers) < 128, 'Decoded HTTP/2 headers exceed budget')
            headers.append((name, value))
        return headers


def header_map(rows, *, initial):
    result = {}
    ordinary_seen = False
    forbidden = {b'connection', b'proxy-connection', b'keep-alive', b'transfer-encoding', b'upgrade'}
    for name, value in rows:
        expect(name and name.lower() == name, 'Invalid uppercase or empty HTTP/2 header name')
        expect(not any(x in value for x in (b'\r', b'\n', b'\x00')), 'Invalid HTTP/2 header value')
        if name.startswith(b':'):
            expect(initial and not ordinary_seen and name == b':status', 'Invalid response pseudo-header placement')
        else:
            ordinary_seen = True
            expect(re.fullmatch(rb"[!#$%&'*+.^_`|~0-9a-z-]+", name) is not None, 'Invalid HTTP/2 header name')
            expect(name not in forbidden, 'Forbidden HTTP/2 connection-specific header')
        text = name.decode('ascii')
        if text in {':status', 'content-type', 'grpc-status', 'grpc-message', 'grpc-encoding'}:
            expect(text not in result, 'Duplicate critical response header: ' + text)
        result.setdefault(text, []).append(value.decode('latin1'))
    if initial:
        expect(result.get(':status') == ['200'], 'HTTP response status is not 200')
        content = result.get('content-type', [])
        expect(len(content) == 1 and content[0].split(';')[0].strip() in {'application/grpc', 'application/grpc+proto'}, 'Response content-type is not gRPC Protobuf')
        expect(result.get('grpc-encoding', ['identity']) == ['identity'], 'Unsupported gRPC compression encoding')
    return result


def read_exact(sock, count, deadline):
    result = bytearray()
    while len(result) < count:
        remaining = deadline - time.monotonic()
        expect(remaining > 0, 'HTTP/2 RPC deadline exceeded')
        sock.settimeout(remaining)
        block = sock.recv(count - len(result))
        expect(bool(block), 'HTTP/2 connection closed before complete response')
        result.extend(block)
    return bytes(result)


def remove_padding(data, flags):
    if not flags & 8:
        return data
    expect(len(data) >= 1 and data[0] < len(data), 'Invalid HTTP/2 padding length')
    return data[1:len(data) - data[0]]


def receive_unary(sock, *, expected_status=0, deadline=None):
    """Read one response; END_STREAM on DATA never substitutes for trailers."""
    if deadline is None:
        deadline = time.monotonic() + RPC_SECONDS
    decoder = HpackDecoder()
    body = bytearray()
    received = []
    initial = trailers = None
    pending = None
    pending_end_stream = False
    settings_seen = ended = False
    for _ in range(MAX_FRAMES):
        head = read_exact(sock, 9, deadline)
        length = int.from_bytes(head[:3], 'big')
        kind, flags = head[3:5]
        stream = int.from_bytes(head[5:9], 'big') & 0x7fffffff
        expect(length <= MAX_FRAME_BYTES, 'HTTP/2 frame exceeds advertised maximum')
        data = read_exact(sock, length, deadline)
        received.append({'type': kind, 'flags': flags, 'stream': stream, 'bytes': length})
        if not settings_seen:
            expect(kind == 4 and stream == 0 and not flags & 1, 'Server preface is not SETTINGS')
            settings_seen = True
        if pending is not None:
            expect(kind == 9 and stream == 1, 'Interrupted HTTP/2 HEADERS/CONTINUATION block')
        if kind == 4:
            expect(stream == 0, 'SETTINGS on a nonzero stream')
            if flags & 1:
                expect(length == 0, 'SETTINGS ACK contains a payload')
            else:
                expect(length % 6 == 0, 'Malformed SETTINGS length')
                for position in range(0, length, 6):
                    key, value = struct.unpack('>HI', data[position:position + 6])
                    expect(key != 2, 'Server must not send SETTINGS_ENABLE_PUSH')
                    expect(key != 4 or value < 2**31, 'Invalid SETTINGS_INITIAL_WINDOW_SIZE')
                    expect(key != 5 or 16384 <= value <= 16777215, 'Invalid SETTINGS_MAX_FRAME_SIZE')
                sock.sendall(frame(4, 1, 0))
            continue
        if kind == 6:
            expect(stream == 0 and length == 8, 'Malformed PING')
            if not flags & 1:
                sock.sendall(frame(6, 1, 0, data))
            continue
        if kind == 8:
            expect(stream in {0, 1} and length == 4 and int.from_bytes(data, 'big') & 0x7fffffff, 'Malformed WINDOW_UPDATE')
            continue
        if kind in {3, 7}:
            raise ProtocolError('HTTP/2 reset or GOAWAY before completed RPC: ' + data.hex())
        if kind == 5:
            raise ProtocolError('Server push is disabled for this fixed RPC')
        if kind not in {0, 1, 2, 9}:
            continue  # RFC 9113 permits unknown extension frame types.
        expect(stream == 1, 'Response frame on an unexpected stream')
        if kind == 2:
            expect(length == 5 and (int.from_bytes(data[:4], 'big') & 0x7fffffff) != stream, 'Malformed PRIORITY frame')
            continue
        if kind == 0:
            expect(initial is not None and trailers is None, 'DATA outside the response body')
            expect(not flags & 1, 'gRPC response ended on DATA without mandatory trailers')
            body.extend(remove_padding(data, flags))
            expect(len(body) <= MAX_BODY_BYTES, 'Unary response body exceeds budget')
            continue
        if kind == 1:
            expect(pending is None and trailers is None, 'Unexpected additional response HEADERS')
            fragment = remove_padding(data, flags)
            if flags & 32:
                expect(len(fragment) >= 5 and (int.from_bytes(fragment[:4], 'big') & 0x7fffffff) != stream, 'Malformed HEADERS priority')
                fragment = fragment[5:]
            pending = bytearray(fragment)
            pending_end_stream = bool(flags & 1)
        else:
            expect(pending is not None, 'Unexpected CONTINUATION without HEADERS')
            pending.extend(data)
        expect(len(pending) <= MAX_HEADER_BYTES, 'Compressed header block exceeds budget')
        if not flags & 4:
            continue
        decoded = decoder.decode(bytes(pending))
        pending = None
        if initial is None:
            initial = header_map(decoded, initial=True)
            if pending_end_stream:
                trailers = initial  # Valid gRPC trailers-only response.
            else:
                expect('grpc-status' not in initial, 'gRPC status appeared before final trailers')
        else:
            expect(pending_end_stream, 'gRPC trailers did not close the stream')
            trailers = header_map(decoded, initial=False)
        if pending_end_stream:
            ended = True
            break
    expect(ended and pending is None and initial is not None and trailers is not None, 'No complete gRPC response with trailers')
    statuses = trailers.get('grpc-status', [])
    expect(len(statuses) == 1 and re.fullmatch(r'0|[1-9][0-9]*', statuses[0]) is not None, 'Missing or malformed grpc-status')
    status = int(statuses[0])
    expect(0 <= status <= 16, 'Unknown grpc-status')
    message = unquote(trailers.get('grpc-message', [''])[0], errors='replace')
    expect(status == expected_status, f'Unexpected grpc-status {status}; expected {expected_status}: {message}')
    messages = []
    offset = 0
    while offset < len(body):
        expect(len(body) - offset >= 5 and body[offset] == 0, 'Unsupported compressed or truncated gRPC message')
        length = int.from_bytes(body[offset + 1:offset + 5], 'big')
        offset += 5
        expect(offset + length <= len(body), 'Truncated gRPC payload')
        messages.append(bytes(body[offset:offset + length]))
        offset += length
    expect(len(messages) == (1 if status == 0 else 0), 'Unexpected unary gRPC response cardinality')
    return messages, {'frames': received, 'headers': initial, 'trailers': trailers, 'grpc_status': status,
                      'grpc_message': message, 'http_status': 200, 'complete_header_blocks': True}


def unary(port, method, message, *, expected_status=0):
    expect(method in {'ListRuns', 'ListScalars', 'ReadScalars'}, 'Unsupported fixture RPC')
    expect(len(message) <= MAX_FRAME_BYTES - 5, 'Fixed request exceeds one bounded frame')
    path = '/tensorboard.data.TensorBoardDataProvider/' + method
    headers = (b'\x83\x86' + b'\x04' + hpack_string(path) + b'\x01' + hpack_string('127.0.0.1:' + str(port))
               + b'\x0f\x10' + hpack_string('application/grpc')
               + b'\x00' + hpack_string('te') + hpack_string('trailers')
               + b'\x00' + hpack_string('grpc-timeout') + hpack_string('5S'))
    payload = b'\x00' + struct.pack('>I', len(message)) + message
    deadline = time.monotonic() + RPC_SECONDS
    with socket.create_connection(('127.0.0.1', port), timeout=RPC_SECONDS) as sock:
        sock.sendall(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n' + frame(4, 0, 0, struct.pack('>HI', 2, 0))
                     + frame(1, 4, 1, headers) + frame(0, 1, 1, payload))
        return receive_unary(sock, expected_status=expected_status, deadline=deadline)


def protobuf_varint(data, offset):
    result = 0
    for count in range(10):
        expect(offset < len(data), 'Truncated protobuf varint')
        byte = data[offset]
        offset += 1
        expect(count < 9 or byte <= 1, 'Overflowing protobuf varint')
        result |= (byte & 127) << (7 * count)
        if not byte & 128:
            return result, offset
    raise ProtocolError('Excessive protobuf varint')


def protobuf_fields(data):
    expect(len(data) <= MAX_BODY_BYTES, 'Protobuf fixture exceeds budget')
    rows = []
    offset = 0
    while offset < len(data):
        key, offset = protobuf_varint(data, offset)
        number, kind = key >> 3, key & 7
        expect(0 < number < 2**29 and len(rows) < 512, 'Invalid or excessive protobuf fields')
        if kind == 0:
            value, offset = protobuf_varint(data, offset)
        else:
            if kind == 2:
                length, offset = protobuf_varint(data, offset)
            else:
                expect(kind in {1, 5}, 'Unsupported protobuf wire type')
                length = 8 if kind == 1 else 4
            expect(offset + length <= len(data), 'Truncated protobuf field')
            value = data[offset:offset + length]
            offset += length
        rows.append((number, kind, value))
    return rows


def values(rows, number, kind):
    matches = [(typ, value) for field_id, typ, value in rows if field_id == number]
    expect(all(typ == kind for typ, _ in matches), 'Unexpected protobuf field encoding')
    return [value for _, value in matches]


def single(rows, number, kind):
    result = values(rows, number, kind)
    expect(len(result) == 1, 'Missing or repeated singular protobuf fixture field')
    return result[0]


def scalar_entry(message):
    outer = protobuf_fields(message)
    runs = values(outer, 1, 2)
    expect(len(runs) == 1, 'Unexpected scalar run cardinality')
    run = protobuf_fields(runs[0])
    expect(single(run, 1, 2) == b'training', 'Scalar response has the wrong run')
    tags = values(run, 2, 2)
    expect(len(tags) == 1, 'Unexpected scalar tag cardinality')
    tag = protobuf_fields(tags[0])
    expect(single(tag, 1, 2) == b'loss/step', 'Scalar response has the wrong tag')
    return protobuf_fields(single(tag, 2, 2))


def probe(module, work):
    server = Path(module.__file__).parent / 'bin/server'
    expect(server.is_file() and server.read_bytes()[:4] == b'\x7fELF', 'Fixed native TensorBoard server missing')
    events = work / 'events/training'
    events.mkdir(parents=True)
    data = event_bytes()
    (events / 'events.out.tfevents.1761850000.cpg').write_bytes(data)
    port_file = work / 'server.port'
    output = work / 'server-output.log'
    argv = [str(server), '--host', '127.0.0.1', '--port', '0', '--port-file', str(port_file),
            '--reload', 'once', '--checksum', '--logdir', str(events.parent), '--die-after-stdin']
    with output.open('wb') as stream:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 12
            while not port_file.exists() and time.monotonic() < deadline:
                expect(process.poll() is None, output.read_text(errors='replace'))
                time.sleep(.05)
            expect(port_file.exists(), 'Native server did not publish its bound port')
            port = int(port_file.read_text())
            expect(1 <= port <= 65535, 'Native server published an invalid port')
            runs, runs_wire = unary(port, 'ListRuns', b'')
            filter_message = field(2, field(1, b'scalars'))
            scalars, scalars_wire = unary(port, 'ListScalars', filter_message)
            points, points_wire = unary(port, 'ReadScalars', filter_message + field(4, varint(8) + varint(10)))
            invalid, invalid_wire = unary(port, 'ListScalars', b'', expected_status=3)
            empty, empty_wire = unary(port, 'ListScalars', field(2, field(1, b'cpg-no-such-plugin')))
            run = protobuf_fields(single(protobuf_fields(runs[0]), 1, 2))
            expect(single(run, 2, 2) == b'training', 'Native server did not return the exact event run')
            expect(struct.unpack('<d', single(run, 3, 1))[0] == 1761850000.0, 'Run start time differs')
            metadata = scalar_entry(scalars[0])
            expect(single(metadata, 1, 0) == 17, 'Scalar maximum step differs')
            expect(struct.unpack('<d', single(metadata, 2, 1))[0] == 1761850001.0, 'Scalar maximum wall time differs')
            values_row = scalar_entry(points[0])
            packed_step = single(values_row, 1, 2)
            step, end = protobuf_varint(packed_step, 0)
            expect(step == 17 and end == len(packed_step), 'Scalar data step differs')
            expect(single(values_row, 2, 2) == struct.pack('<d', 1761850001.0), 'Scalar data wall time differs')
            expect(single(values_row, 3, 2) == struct.pack('<f', 1.25), 'Scalar data value differs')
            expect(invalid == [] and invalid_wire['grpc_status'] == 3, 'Missing plugin filter was not INVALID_ARGUMENT')
            expect(empty == [b''] and empty_wire['grpc_status'] == 0, 'Valid absent plugin was not an empty successful response')
            result = {'checks': ['real-Rust-server', 'CRC32C-checked-local-event-ingestion',
                                 'decoded-HTTP2-headers-and-HPACK', 'mandatory-grpc-trailers',
                                 'ListRuns-exact-run-and-time', 'ListScalars-exact-tag-step-and-time',
                                 'ReadScalars-exact-step-time-value', 'missing-plugin-filter-INVALID_ARGUMENT',
                                 'absent-plugin-empty-OK-distinguished-from-error', 'bounded-server-shutdown'],
                      'event_sha256': hashlib.sha256(data).hexdigest(), 'runs_response_hex': runs[0].hex(),
                      'scalars_response_hex': scalars[0].hex(), 'points_response_hex': points[0].hex(),
                      'run_frames': runs_wire['frames'], 'scalar_frames': scalars_wire['frames'],
                      'invalid_frames': invalid_wire['frames'],
                      'rpc_protocol': {'ListRuns': runs_wire, 'ListScalars': scalars_wire, 'ReadScalars': points_wire,
                                       'missing-filter': invalid_wire, 'absent-plugin': empty_wire},
                      'native_sha256': hashlib.sha256(server.read_bytes()).hexdigest(),
                      'client_scope': 'Bounded stdlib unary HTTP/2 fixture with RFC HPACK, mandatory status/trailers and exact Protobuf values; no new package dependencies.'}
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        expect(process.returncode == 0, output.read_text(errors='replace'))
    result['server_exit_code'] = process.returncode
    return result


# RFC 7541 Appendix A/B normative protocol constants. Generated from the
# retained rfc7541.txt, SHA-256 2239d7f8fb839b69ae2e928e685559b11376888269f131512197a0e3bacf7f7a.
# Authors Roberto Peon and Herve Ruellan, IETF Trust 2015.
# No hpack/grpcio or other runtime dependency is introduced.
_STATIC = (
    (b':authority', b''),
    (b':method', b'GET'),
    (b':method', b'POST'),
    (b':path', b'/'),
    (b':path', b'/index.html'),
    (b':scheme', b'http'),
    (b':scheme', b'https'),
    (b':status', b'200'),
    (b':status', b'204'),
    (b':status', b'206'),
    (b':status', b'304'),
    (b':status', b'400'),
    (b':status', b'404'),
    (b':status', b'500'),
    (b'accept-charset', b''),
    (b'accept-encoding', b'gzip, deflate'),
    (b'accept-language', b''),
    (b'accept-ranges', b''),
    (b'accept', b''),
    (b'access-control-allow-origin', b''),
    (b'age', b''),
    (b'allow', b''),
    (b'authorization', b''),
    (b'cache-control', b''),
    (b'content-disposition', b''),
    (b'content-encoding', b''),
    (b'content-language', b''),
    (b'content-length', b''),
    (b'content-location', b''),
    (b'content-range', b''),
    (b'content-type', b''),
    (b'cookie', b''),
    (b'date', b''),
    (b'etag', b''),
    (b'expect', b''),
    (b'expires', b''),
    (b'from', b''),
    (b'host', b''),
    (b'if-match', b''),
    (b'if-modified-since', b''),
    (b'if-none-match', b''),
    (b'if-range', b''),
    (b'if-unmodified-since', b''),
    (b'last-modified', b''),
    (b'link', b''),
    (b'location', b''),
    (b'max-forwards', b''),
    (b'proxy-authenticate', b''),
    (b'proxy-authorization', b''),
    (b'range', b''),
    (b'referer', b''),
    (b'refresh', b''),
    (b'retry-after', b''),
    (b'server', b''),
    (b'set-cookie', b''),
    (b'strict-transport-security', b''),
    (b'transfer-encoding', b''),
    (b'user-agent', b''),
    (b'vary', b''),
    (b'via', b''),
    (b'www-authenticate', b''),
)
_HUFFMAN_CODES = (
    (0x1ff8, 13), (0x7fffd8, 23), (0xfffffe2, 28), (0xfffffe3, 28), (0xfffffe4, 28), (0xfffffe5, 28), (0xfffffe6, 28), (0xfffffe7, 28),
    (0xfffffe8, 28), (0xffffea, 24), (0x3ffffffc, 30), (0xfffffe9, 28), (0xfffffea, 28), (0x3ffffffd, 30), (0xfffffeb, 28), (0xfffffec, 28),
    (0xfffffed, 28), (0xfffffee, 28), (0xfffffef, 28), (0xffffff0, 28), (0xffffff1, 28), (0xffffff2, 28), (0x3ffffffe, 30), (0xffffff3, 28),
    (0xffffff4, 28), (0xffffff5, 28), (0xffffff6, 28), (0xffffff7, 28), (0xffffff8, 28), (0xffffff9, 28), (0xffffffa, 28), (0xffffffb, 28),
    (0x14, 6), (0x3f8, 10), (0x3f9, 10), (0xffa, 12), (0x1ff9, 13), (0x15, 6), (0xf8, 8), (0x7fa, 11),
    (0x3fa, 10), (0x3fb, 10), (0xf9, 8), (0x7fb, 11), (0xfa, 8), (0x16, 6), (0x17, 6), (0x18, 6),
    (0x0, 5), (0x1, 5), (0x2, 5), (0x19, 6), (0x1a, 6), (0x1b, 6), (0x1c, 6), (0x1d, 6),
    (0x1e, 6), (0x1f, 6), (0x5c, 7), (0xfb, 8), (0x7ffc, 15), (0x20, 6), (0xffb, 12), (0x3fc, 10),
    (0x1ffa, 13), (0x21, 6), (0x5d, 7), (0x5e, 7), (0x5f, 7), (0x60, 7), (0x61, 7), (0x62, 7),
    (0x63, 7), (0x64, 7), (0x65, 7), (0x66, 7), (0x67, 7), (0x68, 7), (0x69, 7), (0x6a, 7),
    (0x6b, 7), (0x6c, 7), (0x6d, 7), (0x6e, 7), (0x6f, 7), (0x70, 7), (0x71, 7), (0x72, 7),
    (0xfc, 8), (0x73, 7), (0xfd, 8), (0x1ffb, 13), (0x7fff0, 19), (0x1ffc, 13), (0x3ffc, 14), (0x22, 6),
    (0x7ffd, 15), (0x3, 5), (0x23, 6), (0x4, 5), (0x24, 6), (0x5, 5), (0x25, 6), (0x26, 6),
    (0x27, 6), (0x6, 5), (0x74, 7), (0x75, 7), (0x28, 6), (0x29, 6), (0x2a, 6), (0x7, 5),
    (0x2b, 6), (0x76, 7), (0x2c, 6), (0x8, 5), (0x9, 5), (0x2d, 6), (0x77, 7), (0x78, 7),
    (0x79, 7), (0x7a, 7), (0x7b, 7), (0x7ffe, 15), (0x7fc, 11), (0x3ffd, 14), (0x1ffd, 13), (0xffffffc, 28),
    (0xfffe6, 20), (0x3fffd2, 22), (0xfffe7, 20), (0xfffe8, 20), (0x3fffd3, 22), (0x3fffd4, 22), (0x3fffd5, 22), (0x7fffd9, 23),
    (0x3fffd6, 22), (0x7fffda, 23), (0x7fffdb, 23), (0x7fffdc, 23), (0x7fffdd, 23), (0x7fffde, 23), (0xffffeb, 24), (0x7fffdf, 23),
    (0xffffec, 24), (0xffffed, 24), (0x3fffd7, 22), (0x7fffe0, 23), (0xffffee, 24), (0x7fffe1, 23), (0x7fffe2, 23), (0x7fffe3, 23),
    (0x7fffe4, 23), (0x1fffdc, 21), (0x3fffd8, 22), (0x7fffe5, 23), (0x3fffd9, 22), (0x7fffe6, 23), (0x7fffe7, 23), (0xffffef, 24),
    (0x3fffda, 22), (0x1fffdd, 21), (0xfffe9, 20), (0x3fffdb, 22), (0x3fffdc, 22), (0x7fffe8, 23), (0x7fffe9, 23), (0x1fffde, 21),
    (0x7fffea, 23), (0x3fffdd, 22), (0x3fffde, 22), (0xfffff0, 24), (0x1fffdf, 21), (0x3fffdf, 22), (0x7fffeb, 23), (0x7fffec, 23),
    (0x1fffe0, 21), (0x1fffe1, 21), (0x3fffe0, 22), (0x1fffe2, 21), (0x7fffed, 23), (0x3fffe1, 22), (0x7fffee, 23), (0x7fffef, 23),
    (0xfffea, 20), (0x3fffe2, 22), (0x3fffe3, 22), (0x3fffe4, 22), (0x7ffff0, 23), (0x3fffe5, 22), (0x3fffe6, 22), (0x7ffff1, 23),
    (0x3ffffe0, 26), (0x3ffffe1, 26), (0xfffeb, 20), (0x7fff1, 19), (0x3fffe7, 22), (0x7ffff2, 23), (0x3fffe8, 22), (0x1ffffec, 25),
    (0x3ffffe2, 26), (0x3ffffe3, 26), (0x3ffffe4, 26), (0x7ffffde, 27), (0x7ffffdf, 27), (0x3ffffe5, 26), (0xfffff1, 24), (0x1ffffed, 25),
    (0x7fff2, 19), (0x1fffe3, 21), (0x3ffffe6, 26), (0x7ffffe0, 27), (0x7ffffe1, 27), (0x3ffffe7, 26), (0x7ffffe2, 27), (0xfffff2, 24),
    (0x1fffe4, 21), (0x1fffe5, 21), (0x3ffffe8, 26), (0x3ffffe9, 26), (0xffffffd, 28), (0x7ffffe3, 27), (0x7ffffe4, 27), (0x7ffffe5, 27),
    (0xfffec, 20), (0xfffff3, 24), (0xfffed, 20), (0x1fffe6, 21), (0x3fffe9, 22), (0x1fffe7, 21), (0x1fffe8, 21), (0x7ffff3, 23),
    (0x3fffea, 22), (0x3fffeb, 22), (0x1ffffee, 25), (0x1ffffef, 25), (0xfffff4, 24), (0xfffff5, 24), (0x3ffffea, 26), (0x7ffff4, 23),
    (0x3ffffeb, 26), (0x7ffffe6, 27), (0x3ffffec, 26), (0x3ffffed, 26), (0x7ffffe7, 27), (0x7ffffe8, 27), (0x7ffffe9, 27), (0x7ffffea, 27),
    (0x7ffffeb, 27), (0xffffffe, 28), (0x7ffffec, 27), (0x7ffffed, 27), (0x7ffffee, 27), (0x7ffffef, 27), (0x7fffff0, 27), (0x3ffffee, 26),
    (0x3fffffff, 30),
)
