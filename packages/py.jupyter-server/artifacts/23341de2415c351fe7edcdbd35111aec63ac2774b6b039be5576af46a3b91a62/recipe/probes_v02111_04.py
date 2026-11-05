"""Bounded local benchmark dispatch, SDK transport, notebook compatibility and server APIs."""
from pathlib import Path
import asyncio,hashlib,http.server,json,os,subprocess,sys,threading,time,urllib.request,urllib.error
from profile_probes import main,PROBES,require,raises

def asv_probe(m,work):
    suite=work/'benchmarks';suite.mkdir();(suite/'__init__.py').write_text('');(suite/'case.py').write_text('def track_total():\n    return sum([2,3,5])\n\ndef time_total():\n    sum(range(100))\n')
    def invoke(args,success=True):
        result=subprocess.run([sys.executable,'-I','-B','-m','asv.benchmark',*map(str,args)],cwd=work,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        require((result.returncode==0)==success,'ASV command exit differs: '+result.stderr)
        return result
    discovered=work/'discovery.json';invoke(['discover',suite,discovered]);rows=json.loads(discovered.read_text());names={x['name'] for x in rows};track=next(x for x in names if x.endswith('track_total'));timed=next(x for x in names if x.endswith('time_total'))
    tracking=work/'tracking.json';invoke(['run',suite,track,'{}','None',tracking]);require(json.loads(tracking.read_text())==10,'ASV tracking result differs')
    timing=work/'timing.json';invoke(['run',suite,timed,json.dumps({'repeat':1,'number':1,'warmup_time':0}),'None',timing]);value=json.loads(timing.read_text());require(value['number']==1 and value['samples'] and all(x>=0 for x in value['samples']),'ASV timing samples differ')
    bad=invoke(['cpg-invalid-command'],False);require('Unknown mode' in bad.stderr,'ASV invalid dispatch lacked refusal')
    return ['benchmark-discovery','actual-tracking-benchmark','exact-result-10','actual-bounded-timing-benchmark','sample-accounting','unknown-command-rejection',{'discovered_names':sorted(names),'timing_samples':value['samples']}]

def cwevals_probe(m,work):
    import httpx
    seen=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append({'path':self.path,'authorization_present':bool(self.headers.get('Authorization'))})
            if 'error=1' in self.path:code=400;body={'error':'cpg-invalid-request'}
            elif 'malformed=1' in self.path:code=200;body={'message':{'not':'text'}}
            else:code=200;body={'message':'cpg-local-service'}
            data=json.dumps(body).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
    try:
        with m.Client(api_key='cpg-local-fixture-only',bearer_token='cpg-local-fixture-bearer',base_url=url,max_retries=0,timeout=5,_strict_response_validation=True,http_client=httpx.Client(trust_env=False)) as client:
            response=client.service.get(extra_query={'probe':'17'});require(response.message=='cpg-local-service','Typed sync SDK response differs')
            raw=client.service.with_raw_response.get();require(raw.status_code==200 and raw.parse().message=='cpg-local-service','Raw response wrapper differs')
            raises(m.BadRequestError,lambda:client.service.get(extra_query={'error':'1'}),'Typed HTTP error missing')
            raises(m.APIResponseValidationError,lambda:client.service.get(extra_query={'malformed':'1'}),'Malformed typed response accepted')
        async def exercise():
            async with m.AsyncClient(api_key='cpg-local-fixture-only',bearer_token='cpg-local-fixture-bearer',base_url=url,max_retries=0,timeout=5,_strict_response_validation=True,http_client=httpx.AsyncClient(trust_env=False)) as client:
                require((await client.service.get()).message=='cpg-local-service','Typed async SDK response differs')
        asyncio.run(exercise());require(any('probe=17' in x['path'] for x in seen) and all(x['authorization_present'] for x in seen),'Request query/auth serialization differs')
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
    require(not thread.is_alive(),'Local HTTP server did not stop')
    return ['loopback-only-SDK-transport','typed-sync-response','raw-response-wrapper','typed-HTTP-400','strict-malformed-response-rejection','typed-async-response','query-auth-serialization','client-and-server-close']

def notebook_shim_probe(m,work):
    from notebook_shim.nbserver import proxy,ClassProxyError,get_nbserver_extensions,diff_members
    from traitlets import HasTraits,Unicode
    class Source(HasTraits):
        value=Unicode('first')
        def greet(self,name):return self.value+':'+name
    class Target:pass
    source=Source();target=Target();require('value' in diff_members(target,source),'Trait difference missing')
    proxy(target,source,'value');proxy(target,source,'greet');require(target.value=='first' and target.greet('probe')=='first:probe','Trait/method proxy differs')
    source.value='second';require(target.value=='second' and target.greet('probe')=='second:probe','Live proxy lost source changes')
    raises(ClassProxyError,lambda:proxy(target,source,'value'),'Duplicate proxy accepted')
    config=work/'config';config.mkdir();(config/'jupyter_notebook_config.json').write_text(json.dumps({'NotebookApp':{'nbserver_extensions':{'cpg_fixture':True,'cpg_disabled':False}}}))
    require(get_nbserver_extensions([str(config)])=={'cpg_fixture':True,'cpg_disabled':False},'Legacy extension configuration differs')
    require(m._jupyter_server_extension_points()==[{'module':'notebook_shim.nbserver'}],'Extension entry differs')
    return ['live-trait-proxy','bound-method-proxy','post-change-proxy-values','duplicate-proxy-rejection','legacy-extension-JSON-config','extension-entry']

def jupyter_service(m,work,lab=False):
    root=work/'documents';runtime=work/'runtime';root.mkdir();runtime.mkdir();token='cpg-local-fixture-token';module='jupyterlab' if lab else 'jupyter_server'
    cmd=[sys.executable,'-I','-B','-m',module,'--no-browser','--allow-root','--ServerApp.ip=127.0.0.1','--ServerApp.port=0','--ServerApp.port_retries=0','--ServerApp.root_dir='+str(root),'--IdentityProvider.token='+token]
    if lab:cmd+=['--LabApp.extension_manager=readonly','--LabApp.watch=False']
    log=work/'server.log'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with log.open('wb') as output:
        process=subprocess.Popen(cmd,cwd=work,stdout=output,stderr=subprocess.STDOUT,env={**os.environ,'PATH':str(Path(sys.prefix)/'bin'),'JUPYTER_RUNTIME_DIR':str(runtime)})
        try:
            deadline=time.monotonic()+35;info=None
            while time.monotonic()<deadline:
                if process.poll() is not None:raise AssertionError('Packaged server exited early: '+log.read_text(errors='replace')[-5000:])
                path=runtime/('jpserver-'+str(process.pid)+'.json')
                if path.exists():
                    try:info=json.loads(path.read_text())
                    except json.JSONDecodeError:pass
                    if info and info.get('port'):break
                time.sleep(.1)
            require(info and info['port']>0,'Server did not publish local port')
            base='http://127.0.0.1:'+str(info['port'])
            def request(path,method='GET',body=None,auth=True):
                headers={'Authorization':'token '+token} if auth else {}
                if body is not None:headers['Content-Type']='application/json'
                q=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
                with opener.open(q,timeout=5) as response:return response.status,response.read()
            status,data=request('/api/status');require(status==200 and isinstance(json.loads(data),dict),'Authenticated status API failed')
            status,data=request('/api/contents/cpg-probe.txt','PUT',{'type':'file','format':'text','content':'ordinary local API content'});require(status in (200,201),'Content creation failed')
            status,data=request('/api/contents/cpg-probe.txt');require(status==200 and json.loads(data)['content']=='ordinary local API content','Content readback differs')
            require((root/'cpg-probe.txt').read_text()=='ordinary local API content','Content API did not write the isolated root')
            require(request('/api/contents/cpg-probe.txt','DELETE')[0]==204,'Content deletion failed')
            try:request('/api/contents/cpg-probe.txt')
            except urllib.error.HTTPError as error:require(error.code==404,'Deleted resource wrong HTTP status')
            else:raise AssertionError('Deleted content still returned')
            try:request('/api/status',auth=False)
            except urllib.error.HTTPError as error:require(error.code in (302,401,403),'Unauthenticated request got unexpected status')
            else:raise AssertionError('Unauthenticated API request accepted')
            if lab:
                status,data=request('/lab');require(status==200 and b'jupyter' in data.lower() and b'<!doctype html' in data.lower(),'Packaged JupyterLab HTML was not served')
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            output.flush()
            print(json.dumps({'nested_server_log':log.read_text(errors='replace'),'scope':'local fixture server only; original raw subprocess log'}))
    require(process.poll() is not None,'Server process did not stop')
    operations=['packaged-loopback-server','private-Python-and-no-host-command-PATH','authenticated-status-API','content-create-read-delete','isolated-filesystem-result','deleted-resource-404','unauthenticated-request-rejection','server-shutdown']
    if lab:operations+=['packaged-Lab-HTML','readonly-extension-manager-no-installation']
    return operations

def server_probe(m,work):return jupyter_service(m,work,False)
def lab_probe(m,work):return jupyter_service(m,work,True)
PROBES.update({'asv':asv_probe,'cwevals':cwevals_probe,'notebook-shim':notebook_shim_probe,'jupyter-server':server_probe,'jupyterlab':lab_probe})
