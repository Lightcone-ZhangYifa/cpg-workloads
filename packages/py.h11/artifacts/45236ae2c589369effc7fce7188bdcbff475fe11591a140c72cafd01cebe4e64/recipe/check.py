#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(h11, work):
    """Exchange actual HTTP/1.1 protocol bytes and validate state/error transitions."""
    client = h11.Connection(h11.CLIENT); server = h11.Connection(h11.SERVER)
    request = client.send(h11.Request(method='GET',target='/fixture',headers=[('Host','localhost')]))
    request += client.send(h11.EndOfMessage())
    for offset in range(0,len(request),3): server.receive_data(request[offset:offset+3])
    received = server.next_event(); require(isinstance(received,h11.Request) and received.method == b'GET' and received.target == b'/fixture', 'Request parse mismatch')
    require(isinstance(server.next_event(),h11.EndOfMessage), 'Request boundary missing')
    response = server.send(h11.Response(status_code=200,headers=[('Content-Length','5')]))
    response += server.send(h11.Data(data=b'hello')) + server.send(h11.EndOfMessage())
    client.receive_data(response)
    require(client.next_event().status_code == 200 and client.next_event().data == b'hello' and isinstance(client.next_event(),h11.EndOfMessage), 'Response/body/boundary mismatch')
    require(client.our_state is h11.DONE and server.our_state is h11.DONE, 'Completed state mismatch')
    client.start_next_cycle(); server.start_next_cycle()
    require(client.our_state is h11.IDLE and server.our_state is h11.IDLE, 'Keep-alive cycle reset failed')
    raises(h11.LocalProtocolError, lambda: h11.Connection(h11.CLIENT).send(h11.Data(data=b'premature')), 'Premature body accepted')
    raises(h11.LocalProtocolError, lambda: h11.Request(method='GET',target='/',headers=[('Host','x'),('Content-Length','2'),('Content-Length','3')]), 'Conflicting lengths accepted')
    broken = h11.Connection(h11.SERVER); broken.receive_data(b'not a valid request\r\n\r\n')
    raises(h11.RemoteProtocolError, broken.next_event, 'Malformed start line accepted')
    return {'checks':['serialized-request','fragmented-input','request-boundary','response-body-boundary','done-state','keepalive-next-cycle','premature-body','conflicting-lengths','invalid-start-line'], 'scope':'in-memory HTTP/1.1 protocol byte exchange; no sockets or TLS'}

if __name__ == "__main__":
    raise SystemExit(main('h11', 'h11', functional))
