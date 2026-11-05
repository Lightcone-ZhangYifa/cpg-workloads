"""Third local functional set, exact original versions and dependency closures."""
from __future__ import annotations
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import sys
import threading
import zipfile
import profile_probes as base
from profile_probes import require, raises


def command(argv, *, timeout=25):
    return subprocess.run(argv,capture_output=True,text=True,timeout=timeout)


def pip_probe(m,work):
    wheel=work/'cpg_offline_fixture-1.0-py3-none-any.whl'
    dist='cpg_offline_fixture-1.0.dist-info'
    members={'cpg_offline_fixture/__init__.py':b'value = 37\n',
             dist+'/METADATA':b'Metadata-Version: 2.1\nName: cpg-offline-fixture\nVersion: 1.0\n',
             dist+'/WHEEL':b'Wheel-Version: 1.0\nGenerator: cpg-local-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
    record=io.StringIO(newline='');writer=csv.writer(record)
    for name,data in members.items():writer.writerow([name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='),len(data)])
    writer.writerow([dist+'/RECORD','','']);members[dist+'/RECORD']=record.getvalue().encode()
    with zipfile.ZipFile(wheel,'w') as archive:
        for name,data in members.items():archive.writestr(name,data)
    pip=[sys.executable,'-I','-B','-m','pip']
    installed=False
    try:
        result=command(pip+['install','--no-index','--no-deps','--no-cache-dir','--disable-pip-version-check',str(wheel)])
        require(result.returncode==0,'Offline fixture installation failed: '+result.stdout+result.stderr);installed=True
        child=command([sys.executable,'-I','-B','-c','import cpg_offline_fixture,importlib.metadata; assert cpg_offline_fixture.value == 37; assert importlib.metadata.version("cpg-offline-fixture") == "1.0"; print("fixture-ok")'])
        require(child.returncode==0 and child.stdout.strip()=='fixture-ok','Installed wheel did not execute: '+child.stderr)
        absent=command(pip+['install','--no-index','--no-deps','--no-cache-dir','--disable-pip-version-check','cpg-certainly-missing-fixture==9999'])
        require(absent.returncode!=0 and 'No matching distribution found' in absent.stderr,'Missing offline distribution was accepted')
    finally:
        if installed:
            removed=command(pip+['uninstall','--yes','--disable-pip-version-check','cpg-offline-fixture'])
            require(removed.returncode==0,'Fixture uninstall failed: '+removed.stdout+removed.stderr)
    raises(importlib.metadata.PackageNotFoundError,lambda:importlib.metadata.distribution('cpg-offline-fixture'),'Fixture metadata survived removal')
    return ['actual-offline-valid-wheel-install','fresh-process-payload-execution','exact-installed-metadata','missing-offline-distribution','fixture-uninstall']


def alembic_probe(m,work):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    engine=sa.create_engine('sqlite+pysqlite:///:memory:')
    try:
        with engine.begin() as connection:
            operation=Operations(MigrationContext.configure(connection))
            operation.create_table('cpg_items',sa.Column('id',sa.Integer,primary_key=True),sa.Column('name',sa.String(40),nullable=False))
            connection.execute(sa.text('INSERT INTO cpg_items (id,name) VALUES (:id,:name)'),{'id':7,'name':'compiler'})
            operation.add_column('cpg_items',sa.Column('score',sa.Integer,nullable=False,server_default='3'))
            require(connection.execute(sa.text('SELECT id,name,score FROM cpg_items')).one()==(7,'compiler',3),'Migration changed row content')
            require({x['name'] for x in sa.inspect(connection).get_columns('cpg_items')}=={'id','name','score'},'Migrated schema differs')
            raises(sa.exc.OperationalError,lambda:operation.create_table('cpg_items',sa.Column('id',sa.Integer)),'Duplicate table migration was accepted')
            operation.drop_table('cpg_items')
            require('cpg_items' not in sa.inspect(connection).get_table_names(),'Migration drop left table behind')
    finally:engine.dispose()
    return ['real-sqlite-migration-context','table-create','preserved-data','add-column-default','duplicate-table-rejection','table-drop']


def virtualenv_probe(m,work):
    prefix=work/'child-environment'
    common=[sys.executable,'-I','-B','-m','virtualenv','--no-download','--no-seed','--copies','--app-data',str(work/'app-data')]
    result=command(common+[str(prefix)],timeout=45)
    require(result.returncode==0,'Private virtualenv creation failed: '+result.stdout+result.stderr)
    child=prefix/'bin/python'
    require(child.is_file() and not child.is_symlink() and child.stat().st_nlink==1 and not os.path.samefile(child,sys.executable),'Virtualenv interpreter is not an independent copy')
    result=command([str(child),'-I','-B','-c','import json,sys; print(json.dumps({"prefix":sys.prefix,"base_prefix":sys.base_prefix,"value":sum([2,3,5])}))'])
    require(result.returncode==0,'Created interpreter did not execute: '+result.stderr)
    info=json.loads(result.stdout);require(Path(info['prefix']).resolve()==prefix.resolve() and info['prefix']!=info['base_prefix'] and info['value']==10,'Created interpreter isolation differs')
    invalid=command(common+['--creator','cpg-invalid-creator',str(work/'invalid')])
    require(invalid.returncode!=0 and 'cpg-invalid-creator' in invalid.stderr+invalid.stdout and not (work/'invalid').exists(),'Invalid creator was accepted')
    return ['actual-no-download-no-seed-virtualenv','independent-interpreter-copy','child-interpreter-execution','prefix-isolation','invalid-creator-rejection']


def check_jsonschema_probe(m,work):
    schema=work/'schema.json';valid=work/'valid.json';invalid=work/'invalid.json'
    schema.write_text(json.dumps({'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['seed'],'properties':{'seed':{'type':'integer','minimum':1}},'additionalProperties':False}))
    valid.write_text('{"seed": 7}');invalid.write_text('{"seed": "wrong"}')
    cli=[sys.executable,'-I','-B','-m','check_jsonschema','--schemafile',str(schema)]
    good=command(cli+[str(valid)]);bad=command(cli+[str(invalid)])
    require(good.returncode==0,'Valid local JSON document was rejected: '+good.stdout+good.stderr)
    require(bad.returncode!=0 and 'seed' in bad.stdout+bad.stderr,'Invalid local JSON document was accepted')
    schema.write_text('{"type": "cpg-invalid-type"}')
    broken=command(cli+[str(valid)])
    require(broken.returncode!=0 and 'cpg-invalid-type' in broken.stdout+broken.stderr,'Malformed schema was accepted')
    return ['real-cli-local-schema','valid-document','invalid-type-rejection','invalid-schema-rejection']


@contextmanager
def local_endpoint(callback):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle_request(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            status,headers,payload=callback(self.command,self.path,dict(self.headers),body)
            self.send_response(status)
            for key,value in headers.items():self.send_header(key,value)
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        do_GET=handle_request;do_POST=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join(timeout=3);require(not thread.is_alive(),'Local fixture server did not stop')


def httpx2_probe(m,work):
    def respond(method,path,headers,body):
        if path=='/error':return 400,{'Content-Type':'application/json'},b'{"error":"fixture"}'
        if path=='/invalid-json':return 200,{'Content-Type':'application/json'},b'not-json'
        return 200,{'Content-Type':'application/json'},json.dumps({'method':method,'path':path,'body':body.decode()}).encode()
    with local_endpoint(respond) as endpoint:
        with m.Client(trust_env=False,timeout=3) as client:
            response=client.get(endpoint+'/items',params={'q':'compiler'})
            require(response.status_code==200 and response.json()['path']=='/items?q=compiler','Actual GET query differs')
            posted=client.post(endpoint+'/items',json={'seed':7})
            require(posted.status_code==200 and json.loads(posted.json()['body'])=={'seed':7},'Actual JSON POST differs')
            error=client.get(endpoint+'/error')
            raises(m.HTTPStatusError,error.raise_for_status,'HTTP error status was accepted')
            malformed=client.get(endpoint+'/invalid-json')
            raises(ValueError,malformed.json,'Malformed response JSON was accepted')
    return ['actual-loopback-client','query-serialization','json-request-response','http-error-rejection','invalid-json','client-close']


def huggingface_probe(m,work):
    seen=[]
    info={'id':'cpg/model','sha':'0123456789abcdef0123456789abcdef01234567','private':False,'downloads':1,'tags':[],'siblings':[]}
    def respond(method,path,headers,body):
        seen.append((method,path))
        if path.split('?')[0]=='/api/models':data=[info];status=200
        elif path=='/api/models/cpg/model':data=info;status=200
        else:data={'error':'local missing model'};status=404
        return status,{'Content-Type':'application/json'},json.dumps(data).encode()
    with local_endpoint(respond) as endpoint:
        api=m.HfApi(endpoint=endpoint,token=False)
        listed=list(api.list_models(limit=1));require(len(listed)==1 and listed[0].id=='cpg/model','Actual local model listing differs')
        model=api.model_info('cpg/model');require(model.id=='cpg/model' and model.sha==info['sha'],'Actual local model metadata differs')
        from huggingface_hub.errors import HfHubHTTPError
        from huggingface_hub.utils import HFValidationError
        raises(HfHubHTTPError,lambda:api.model_info('cpg/missing'),'Missing model response was accepted')
        count=len(seen);raises(HFValidationError,lambda:api.model_info('bad space'),'Invalid repo identifier was accepted')
        require(len(seen)==count,'Invalid repository identifier made a network request')
    require(len(seen)==3 and all(method=='GET' for method,path in seen),'Unexpected local API request sequence')
    return {'checks':['real-local-model-list-client','typed-model-metadata','http-missing-model','invalid-repo-id-before-network'],
            'scope':'Local Hub metadata protocol client only. No public Hub access, authentication, upload, model execution or Xet/CAS transfer qualification.'}


def otlp_http_probe(m,work):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    import requests
    captured=[]
    def respond(method,path,headers,body):
        captured.append((method,path,headers,body))
        return (400 if path=='/reject' else 200),{'Content-Type':'application/x-protobuf'},b''
    with local_endpoint(respond) as endpoint:
        session=requests.Session();session.trust_env=False
        exporter=m.OTLPSpanExporter(endpoint=endpoint+'/v1/traces',session=session,timeout=3)
        memory=InMemorySpanExporter();provider=TracerProvider(sampler=ALWAYS_ON);provider.add_span_processor(SimpleSpanProcessor(exporter));provider.add_span_processor(SimpleSpanProcessor(memory))
        try:
            with provider.get_tracer('cpg-local').start_as_current_span('compile-fixture') as span:span.set_attribute('cpg.seed',7)
            require(provider.force_flush(timeout_millis=3000),'OTLP provider did not flush')
            require(len(captured)==1 and captured[0][0:2]==('POST','/v1/traces'),'Actual exporter HTTP request differs')
            message=ExportTraceServiceRequest.FromString(captured[0][3]);decoded=message.resource_spans[0].scope_spans[0].spans[0]
            require(decoded.name=='compile-fixture' and any(x.key=='cpg.seed' and x.value.int_value==7 for x in decoded.attributes),'Transmitted OTLP span payload differs')
            bad_session=requests.Session();bad_session.trust_env=False
            rejected=m.OTLPSpanExporter(endpoint=endpoint+'/reject',session=bad_session,timeout=3)
            try:require(rejected.export(memory.get_finished_spans())==SpanExportResult.FAILURE,'Permanent collector error was accepted')
            finally:rejected.shutdown()
            require(len(captured)==2 and captured[-1][1]=='/reject','Permanent collector failure retried unexpectedly')
        finally:provider.shutdown()
    return ['actual-sdk-span-lifecycle','real-loopback-otlp-http-export','protobuf-span-payload','attribute-encoding','permanent-http-error','flush-and-shutdown']


PROBES={'pip':pip_probe,'alembic':alembic_probe,'virtualenv':virtualenv_probe,'check-jsonschema':check_jsonschema_probe,
        'httpx2':httpx2_probe,'huggingface-hub':huggingface_probe,'opentelemetry-exporter-otlp-proto-http':otlp_http_probe}
base.PROBES.update(PROBES)
main=base.main
