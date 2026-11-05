#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(httpx, work):
    """Exercise real local HTTP requests, redirects, gzip and status/data errors."""
    from http_fixture import local_server
    with local_server() as base, httpx.Client(trust_env=False,timeout=2) as client:
        response = client.get(base+'/ok',headers={'X-Check':'verified'},params={'q':'compiler'})
        require(response.status_code == 200 and response.json()['header'] == 'verified' and 'q=compiler' in response.json()['path'], 'HTTP GET/header/query failed')
        posted = client.post(base+'/echo',json={'values':[1,2,3]})
        require(posted.json() == {'values':[1,2,3]}, 'HTTP JSON POST failed')
        redirect = client.get(base+'/redirect',follow_redirects=True)
        require(redirect.status_code == 200 and len(redirect.history) == 1 and redirect.url.path == '/ok', 'Redirect contract failed')
        compressed = client.get(base+'/gzip')
        require(compressed.json() == {'compressed':True}, 'Gzip response decoding failed')
        raises(httpx.HTTPStatusError, lambda: client.get(base+'/error').raise_for_status(), 'HTTP 503 was not raised')
        raises(ValueError, lambda: client.get(base+'/invalid-json').json(), 'Malformed JSON accepted')
        raises(httpx.UnsupportedProtocol, lambda: client.get('cpg-unsupported://localhost'), 'Unsupported scheme accepted')
    return {'checks':['real-loopback-get','headers-and-query','json-post','redirect-history','gzip-decoding','error-status','malformed-json','unsupported-protocol','client-and-server-close'], 'scope':'local plain HTTP only; TLS, remote servers and HTTP/2 not exercised'}

if __name__ == "__main__":
    raise SystemExit(main('httpx', 'httpx', functional))
