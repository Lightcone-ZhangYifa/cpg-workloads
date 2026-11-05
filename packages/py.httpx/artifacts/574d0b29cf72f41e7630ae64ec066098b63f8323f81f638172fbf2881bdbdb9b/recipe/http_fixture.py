"""Bounded loopback fixture; explicitly closes the socket and joins its server thread."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import gzip
import json
import threading

@contextmanager
def local_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,status,payload,headers=None):
            self.send_response(status)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Content-Type','application/json')
            for key,value in (headers or {}).items(): self.send_header(key,value)
            self.end_headers(); self.wfile.write(payload)
        def do_GET(self):
            if self.path == '/redirect': self.respond(302,b'',{'Location':'/ok'})
            elif self.path == '/error': self.respond(503,b'{"error":"fixture"}')
            elif self.path == '/invalid-json': self.respond(200,b'{invalid')
            elif self.path == '/gzip': self.respond(200,gzip.compress(b'{"compressed":true}'),{'Content-Encoding':'gzip'})
            else: self.respond(200,json.dumps({'path':self.path,'header':self.headers.get('X-Check')}).encode())
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length','0')))
            try: value = json.loads(raw)
            except ValueError: self.respond(400,b'{"error":"invalid-json"}')
            else: self.respond(200,json.dumps(value).encode())
    server = HTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=0.01),name='cpg-local-http',daemon=False)
    thread.start()
    try: yield 'http://127.0.0.1:'+str(server.server_address[1])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        if thread.is_alive(): raise RuntimeError('Local HTTP fixture failed to join')
