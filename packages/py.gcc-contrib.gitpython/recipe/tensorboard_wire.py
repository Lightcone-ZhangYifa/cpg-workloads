"""Local TensorBoard gRPC integration using a bounded stdlib HTTP/2 client.

Protocol references: grpc/grpc doc/PROTOCOL-HTTP2.md and RFC 7541 Appendix A.
The client only implements the fixed unary requests required by this probe.
It is not a general HTTP/2 or gRPC implementation.
"""
from pathlib import Path
import hashlib
import socket
import struct
import subprocess
import time


def varint(number):
    value = bytearray()
    while number >= 128:
        value.append((number & 127) | 128); number >>= 7
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
    assert hashlib.sha256(data).hexdigest() == '5bf8a8a4250f7c5b7be0546e4b79aee551b40b30799c7a1f39c361a94703f0dc'
    return data


def frame(kind, flags, stream, data=b''):
    return len(data).to_bytes(3, 'big') + bytes([kind, flags]) + struct.pack('>I', stream) + data


def hpack_string(value):
    data = value.encode('ascii')
    assert len(data) < 127
    return bytes([len(data)]) + data


def read_exact(sock, count):
    result = bytearray()
    while len(result) < count:
        block = sock.recv(count - len(result))
        if not block:
            raise RuntimeError('HTTP/2 connection closed before the complete frame')
        result.extend(block)
    return bytes(result)


def unary(port, method, message):
    path = '/tensorboard.data.TensorBoardDataProvider/' + method
    # Indexed POST and http, followed by literal :path, :authority,
    # content-type, and te. No dynamic table or Huffman encoding is used.
    headers = (b'\x83\x86' + b'\x04' + hpack_string(path) + b'\x01' + hpack_string('127.0.0.1:' + str(port))
               + b'\x0f\x10' + hpack_string('application/grpc')
               + b'\x00' + hpack_string('te') + hpack_string('trailers'))
    payload = b'\x00' + struct.pack('>I', len(message)) + message
    with socket.create_connection(('127.0.0.1', port), timeout=5) as sock:
        sock.sendall(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n' + frame(4, 0, 0)
                     + frame(1, 4, 1, headers) + frame(0, 1, 1, payload))
        response = bytearray(); headers_seen = 0; ended = False; received = []
        for _ in range(32):
            head = read_exact(sock, 9)
            length = int.from_bytes(head[:3], 'big'); kind, flags = head[3:5]
            stream = int.from_bytes(head[5:9], 'big') & 0x7fffffff
            assert length <= 1024 * 1024, 'Unbounded response frame'
            data = read_exact(sock, length)
            received.append({'type': kind, 'flags': flags, 'stream': stream, 'bytes': length})
            if kind == 4 and not flags & 1:
                sock.sendall(frame(4, 1, 0))
            elif kind == 6 and not flags & 1:
                sock.sendall(frame(6, 1, 0, data))
            elif kind in (3, 7):
                raise AssertionError('Unexpected HTTP/2 reset or GOAWAY: ' + data.hex())
            if stream == 1:
                if kind == 1:
                    headers_seen += 1
                if kind == 0:
                    if flags & 8:
                        padding = data[0]; data = data[1:len(data)-padding]
                    response.extend(data)
                if kind in (0, 1) and flags & 1:
                    ended = True; break
        assert ended and headers_seen, 'No complete unary stream response'
    messages = []; remaining = bytes(response)
    while remaining:
        assert len(remaining) >= 5 and remaining[0] == 0, 'Unexpected compressed or incomplete gRPC payload'
        length = int.from_bytes(remaining[1:5], 'big')
        assert len(remaining) >= 5 + length
        messages.append(remaining[5:5+length]); remaining = remaining[5+length:]
    return messages, received


def probe(module, work):
    server = Path(module.__file__).parent / 'bin/server'
    assert server.is_file() and server.read_bytes()[:4] == b'\x7fELF'
    events = work / 'events/training'; events.mkdir(parents=True)
    data = event_bytes(); (events / 'events.out.tfevents.1761850000.cpg').write_bytes(data)
    port_file = work / 'server.port'; output = work / 'server-output.log'
    argv = [str(server), '--host', '127.0.0.1', '--port', '0', '--port-file', str(port_file),
            '--reload', 'once', '--checksum', '--logdir', str(events.parent), '--die-after-stdin']
    with output.open('wb') as stream:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 12
            while not port_file.exists() and time.monotonic() < deadline:
                assert process.poll() is None, output.read_text(errors='replace')
                time.sleep(.05)
            assert port_file.exists(), 'Native server did not publish its bound port'
            port = int(port_file.read_text())
            runs, run_frames = unary(port, 'ListRuns', b'')
            scalars, scalar_frames = unary(port, 'ListScalars', field(2, field(1, b'scalars')))
            invalid, invalid_frames = unary(port, 'ListScalars', b'')
            assert len(runs) == 1 and b'training' in runs[0], 'Native server did not load the event run'
            assert len(scalars) == 1 and b'loss/step' in scalars[0], 'Native server did not expose the scalar'
            assert invalid == [], 'Missing plugin filter incorrectly produced a successful scalar payload'
            result = {'checks': ['real-Rust-server', 'CRC32C-checked-local-event-ingestion', 'HTTP2-gRPC-ListRuns',
                                 'HTTP2-gRPC-ListScalars', 'missing-plugin-filter-no-success-payload', 'bounded-server-shutdown'],
                      'event_sha256': hashlib.sha256(data).hexdigest(), 'runs_response_hex': runs[0].hex(),
                      'scalars_response_hex': scalars[0].hex(), 'run_frames': run_frames,
                      'scalar_frames': scalar_frames, 'invalid_frames': invalid_frames,
                      'native_sha256': hashlib.sha256(server.read_bytes()).hexdigest(),
                      'client_scope': 'Fixed unary stdlib HTTP/2 fixture; response HPACK trailer text is not decoded or claimed.'}
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        assert process.returncode == 0, output.read_text(errors='replace')
    result['server_exit_code'] = process.returncode
    return result
