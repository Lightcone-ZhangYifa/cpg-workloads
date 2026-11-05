#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(requests, work):
    """Exercise a real local HTTP session with redirects, gzip and negative inputs."""
    from http_fixture import local_server
    with local_server() as base, requests.Session() as session:
        session.trust_env = False
        response = session.get(base+'/ok',headers={'X-Check':'verified'},params={'q':'compiler'},timeout=2)
        require(response.status_code == 200 and response.json()['header'] == 'verified' and 'q=compiler' in response.json()['path'], 'HTTP GET/header/query failed')
        posted = session.post(base+'/echo',json={'values':[1,2,3]},timeout=2)
        require(posted.json() == {'values':[1,2,3]}, 'JSON request/response failed')
        redirected = session.get(base+'/redirect',timeout=2)
        require(redirected.status_code == 200 and len(redirected.history) == 1 and redirected.url.endswith('/ok'), 'Redirect/history failed')
        require(session.get(base+'/gzip',timeout=2).json() == {'compressed':True}, 'Gzip decoding failed')
        raises(requests.HTTPError, lambda: session.get(base+'/error',timeout=2).raise_for_status(), 'HTTP status error ignored')
        raises(requests.exceptions.JSONDecodeError, lambda: session.get(base+'/invalid-json',timeout=2).json(), 'Invalid JSON accepted')
        raises(requests.exceptions.InvalidSchema, lambda: session.get('cpg-unsupported://localhost',timeout=2), 'Unsupported URL scheme accepted')
    return {'checks':['real-loopback-session','headers-and-query','json-post','redirect-history','gzip-decoding','status-error','invalid-json','invalid-scheme','session-and-server-close'], 'scope':'local plain HTTP only; remote servers, TLS and proxy behavior not exercised'}

if __name__ == "__main__":
    raise SystemExit(main('requests', 'requests', functional))
