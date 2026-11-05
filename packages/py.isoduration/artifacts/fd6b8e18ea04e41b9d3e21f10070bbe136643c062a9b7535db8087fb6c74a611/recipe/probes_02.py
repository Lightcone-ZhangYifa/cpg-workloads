"""Additional bounded local API and command contracts for original resources."""
from __future__ import annotations
from pathlib import Path
import datetime
import io
import json
import os
import subprocess
import sys
import textwrap
import time
import zipfile
import profile_probes as base
from profile_probes import require,raises,local_module


def alive_probe(m,work):
    stream=io.StringIO()
    with m.alive_bar(3,file=stream,force_tty=False,title='CPG') as bar:
        for _ in range(3):bar()
        require(bar.current==3,'Progress position differs')
    require('CPG' in stream.getvalue() and '3/3' in stream.getvalue(),'Final progress rendering differs')
    def invalid():
        with m.alive_bar(1,spinner='cpg-invalid-spinner',file=io.StringIO()):pass
    raises(ValueError,invalid,'Unknown spinner was accepted')
    return ['actual-progress-context','increment-count','rendered-completion','invalid-spinner']


def argon2_probe(m,work):
    hasher=m.PasswordHasher(time_cost=1,memory_cost=8192,parallelism=1,hash_len=16,salt_len=16)
    encoded=hasher.hash('local test password')
    require(hasher.verify(encoded,'local test password'),'Argon2 password verification failed')
    require(not hasher.check_needs_rehash(encoded),'Identical parameters unexpectedly require rehash')
    require(m.PasswordHasher(time_cost=2,memory_cost=8192,parallelism=1).check_needs_rehash(encoded),'Changed work factor was not detected')
    raises(m.exceptions.VerifyMismatchError,lambda:hasher.verify(encoded,'wrong password'),'Wrong password was accepted')
    raises(m.exceptions.InvalidHashError,lambda:hasher.verify('not-an-argon2-hash','test'),'Malformed encoded hash was accepted')
    return ['native-password-hash','password-verification','rehash-parameters','wrong-password','malformed-hash']


def argon2_bindings_probe(m,work):
    ffi,lib=m.ffi,m.lib;password=b'cpg local input';salt=b'12345678abcdefgh'
    digest=ffi.new('unsigned char[]',32);encoded=ffi.new('char[]',256)
    result=lib.argon2_hash(1,8192,1,password,len(password),salt,len(salt),digest,32,encoded,256,lib.Argon2_id,lib.ARGON2_VERSION_NUMBER)
    require(result==lib.ARGON2_OK,'Native argon2_hash failed')
    require(lib.argon2_verify(encoded,password,len(password),lib.Argon2_id)==lib.ARGON2_OK,'Native hash did not verify')
    require(lib.argon2_verify(encoded,b'wrong',5,lib.Argon2_id)==lib.ARGON2_VERIFY_MISMATCH,'Native verifier accepted wrong input')
    result=lib.argon2_hash(1,8192,1,password,len(password),b'x',1,digest,32,encoded,256,lib.Argon2_id,lib.ARGON2_VERSION_NUMBER)
    require(result==lib.ARGON2_SALT_TOO_SHORT,'Native hash accepted undersized salt')
    return ['real-cffi-native-hash','native-verify','wrong-password-rejection','short-salt-error']


def build_probe(m,work):
    project=work/'project';project.mkdir();output=work/'dist';output.mkdir()
    (project/'pyproject.toml').write_text('[build-system]\nrequires = []\nbuild-backend = "local_backend"\nbackend-path = ["."]\n')
    (project/'local_backend.py').write_text('''from pathlib import Path\nimport zipfile\ndef get_requires_for_build_wheel(config_settings=None):return []\ndef build_wheel(wheel_directory,config_settings=None,metadata_directory=None):\n name="cpg_fixture-1.0-py3-none-any.whl"\n with zipfile.ZipFile(Path(wheel_directory)/name,"w") as z:\n  z.writestr("cpg_fixture/__init__.py","value=17\\n")\n  z.writestr("cpg_fixture-1.0.dist-info/METADATA","Metadata-Version: 2.1\\nName: cpg-fixture\\nVersion: 1.0\\n")\n  z.writestr("cpg_fixture-1.0.dist-info/WHEEL","Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")\n return name\n''')
    builder=m.ProjectBuilder(str(project),python_executable=sys.executable)
    require(builder.get_requires_for_build('wheel')==set(),'Local backend unexpectedly requires dependencies')
    artifact=Path(builder.build('wheel',str(output)))
    with zipfile.ZipFile(artifact) as wheel:require(wheel.read('cpg_fixture/__init__.py')==b'value=17\n','Built wheel payload differs')
    (project/'pyproject.toml').write_text('[build-system]\nrequires = []\nbuild-backend = "missing_cpg_backend"\nbackend-path = ["."]\n')
    broken=m.ProjectBuilder(str(project),python_executable=sys.executable)
    raises(m.BuildBackendException,lambda:broken.build('wheel',str(output)),'Missing build backend was accepted')
    return ['actual-pep517-backend-process','declared-empty-backend-requirements','local-wheel-build','wheel-payload','missing-backend']


def google_protos_probe(m,work):
    from google.protobuf.any_pb2 import Any
    from google.protobuf.json_format import MessageToDict
    from google.protobuf.message import DecodeError
    from google.rpc import error_details_pb2
    detail=error_details_pb2.BadRequest();detail.field_violations.add(field='seed',description='must be positive')
    wrapped=Any();wrapped.Pack(detail)
    message=m.Status(code=3,message='invalid local request',details=[wrapped])
    restored=m.Status.FromString(message.SerializeToString())
    require(restored.code==3 and restored.message==message.message,'Status protobuf roundtrip differs')
    unpacked=error_details_pb2.BadRequest();require(restored.details[0].Unpack(unpacked),'Typed error detail did not unpack')
    require(unpacked.field_violations[0].field=='seed','Error detail content differs')
    require(MessageToDict(restored)['code']==3,'Protobuf JSON conversion differs')
    raises(DecodeError,lambda:m.Status.FromString(b'\x80'),'Malformed protobuf was accepted')
    return ['status-protobuf-roundtrip','typed-error-details','any-pack-unpack','protobuf-json','malformed-wire-data']


def grpc_probe(m,work):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        server=m.server(pool)
        handler=m.method_handlers_generic_handler('cpg.Local',{'Echo':m.unary_unary_rpc_method_handler(lambda request,context:request.upper())})
        server.add_generic_rpc_handlers((handler,));port=server.add_insecure_port('127.0.0.1:0')
        require(port>0,'Local gRPC bind failed');server.start()
        try:
            with m.insecure_channel('127.0.0.1:'+str(port)) as channel:
                require(channel.unary_unary('/cpg.Local/Echo')(b'compiler',timeout=3)==b'COMPILER','Actual gRPC request/response differs')
                try:channel.unary_unary('/cpg.Local/Missing')(b'',timeout=3)
                except m.RpcError as error:require(error.code()==m.StatusCode.UNIMPLEMENTED,'Missing method returned wrong gRPC status')
                else:raise AssertionError('Missing gRPC method was accepted')
        finally:require(server.stop(0).wait(3),'Local gRPC server did not stop')
    return ['real-loopback-grpc-server','unary-rpc','missing-method-status','channel-close','server-stop']


def isoduration_probe(m,work):
    value=m.parse_duration('P1Y2M3DT4H5M6S')
    require(m.format_duration(value)=='P1Y2M3DT4H5M6S','ISO duration roundtrip differs')
    one_day=m.parse_duration('P1D')
    require(datetime.datetime(2024,2,28)+one_day==datetime.datetime(2024,2,29),'Duration calendar arithmetic differs')
    raises(m.DurationParsingException,lambda:m.parse_duration('Pwrong'),'Malformed duration was accepted')
    return ['iso-duration-parse','duration-format','leap-year-calendar-addition','malformed-duration']


def cryptography_probe(m,work):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.exceptions import InvalidTag,InvalidSignature
    cipher=AESGCM(bytes(range(32)));nonce=bytes(range(12));message=b'bounded local cryptography operation';aad=b'cpg'
    ciphertext=cipher.encrypt(nonce,message,aad)
    require(cipher.decrypt(nonce,ciphertext,aad)==message,'Authenticated encryption roundtrip differs')
    damaged=ciphertext[:-1]+bytes([ciphertext[-1]^1])
    raises(InvalidTag,lambda:cipher.decrypt(nonce,damaged,aad),'Damaged authentication tag was accepted')
    private=Ed25519PrivateKey.generate();signature=private.sign(message)
    private.public_key().verify(signature,message)
    raises(InvalidSignature,lambda:private.public_key().verify(signature,message+b'x'),'Modified signed message was accepted')
    return ['native-aes-gcm-encrypt-decrypt','authentication-tag-rejection','ed25519-sign-verify','invalid-signature']


def ml_dtypes_probe(m,work):
    import numpy as np
    values=np.array([1,2,3],dtype=m.bfloat16)
    require(values.dtype.itemsize==2 and np.array_equal(values.astype(np.float32),[1,2,3]),'bfloat16 storage/conversion differs')
    require(float(values.sum())==6.,'bfloat16 reduction differs')
    low=np.array([0.,1.,2.],dtype=m.float8_e4m3fn)
    require(low.dtype.itemsize==1 and np.array_equal(low.astype(np.float32),[0,1,2]),'float8 storage/conversion differs')
    require(np.isnan(m.bfloat16(float('nan'))),'bfloat16 NaN classification differs')
    raises(ValueError,lambda:m.bfloat16('not-a-number'),'Invalid numeric input was accepted')
    return ['native-bfloat16-array','float32-conversion','numeric-reduction','native-float8-array','nan','invalid-number']


def otel_http_probe(m,work):
    from opentelemetry.exporter.http.transport._requests import RequestsHTTPTransport
    from http_fixture import local_server
    import requests
    session=requests.Session();session.trust_env=False;transport=RequestsHTTPTransport(session=session)
    try:
        with local_server() as endpoint:
            result=transport.request('GET',endpoint+'/ok',timeout=3)
            require(result.status_code==200 and result.json()['path']=='/ok','Actual exporter HTTP transport response differs')
            error=transport.request('GET',endpoint+'/error',timeout=3)
            require(error.status_code==503 and error.json()['error']=='fixture','Exporter HTTP status propagation differs')
            malformed=transport.request('GET',endpoint+'/invalid-json',timeout=3)
            raises(ValueError,malformed.json,'Invalid response JSON was accepted')
        result=transport.request('GET','cpg-unsupported://localhost/',timeout=1)
        require(result.error is not None and result.status_code is None,'Transport exception was not captured')
    finally:transport.close()
    return ['real-loopback-exporter-transport','response-body','status-propagation','invalid-json','captured-transport-error','transport-close']


def otel_common_probe(m,work):
    from opentelemetry.exporter.otlp.common._aggregation import _get_aggregation,_get_temporality
    from opentelemetry.sdk.metrics import Counter,Histogram,UpDownCounter
    from opentelemetry.sdk.metrics.export import AggregationTemporality
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation,ExponentialBucketHistogramAggregation
    key='OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE';hist='OTEL_EXPORTER_OTLP_METRICS_DEFAULT_HISTOGRAM_AGGREGATION'
    original={k:os.environ.get(k) for k in (key,hist)}
    try:
        os.environ[key]='DELTA';result=_get_temporality(None)
        require(result[Counter]==AggregationTemporality.DELTA and result[UpDownCounter]==AggregationTemporality.CUMULATIVE,'Instrument temporality mapping differs')
        overridden=_get_temporality({Counter:AggregationTemporality.CUMULATIVE})
        require(overridden[Counter]==AggregationTemporality.CUMULATIVE,'Explicit temporality override was lost')
        os.environ[hist]='BASE2_EXPONENTIAL_BUCKET_HISTOGRAM'
        require(isinstance(_get_aggregation(None)[Histogram],ExponentialBucketHistogramAggregation),'Exponential histogram selection failed')
        os.environ[key]='invalid-cpg';os.environ[hist]='invalid-cpg'
        require(_get_temporality(None)[Counter]==AggregationTemporality.CUMULATIVE,'Invalid temporality did not use specified fallback')
        require(isinstance(_get_aggregation(None)[Histogram],ExplicitBucketHistogramAggregation),'Invalid histogram did not use specified fallback')
    finally:
        for key,value in original.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
    return ['instrument-temporality-selection','explicit-override','histogram-aggregation-selection','invalid-setting-fallbacks']


def otel_proto_common_probe(m,work):
    from opentelemetry.exporter.otlp.proto.common._internal import _encode_value,_encode_trace_id,_encode_span_id
    value=_encode_value({'name':'cpg','items':[1,True]})
    require(value.kvlist_value.values[0].key=='name','Attribute map encoding differs')
    require(_encode_trace_id(1)==b'\0'*15+b'\1' and _encode_span_id(1)==b'\0'*7+b'\1','Trace/span ID encoding differs')
    raises(OverflowError,lambda:_encode_span_id(-1),'Negative span ID was accepted')
    raises(Exception,lambda:_encode_value(object()),'Unsupported attribute value was accepted')
    return ['attribute-protobuf-encoding','trace-id-bytes','span-id-bytes','invalid-id','unsupported-value']


def otel_proto_probe(m,work):
    from opentelemetry.proto.trace.v1.trace_pb2 import Span,ResourceSpans,ScopeSpans
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from google.protobuf.message import DecodeError
    span=Span(trace_id=b'1'*16,span_id=b'2'*8,name='local-operation',start_time_unix_nano=1,end_time_unix_nano=2)
    request=ExportTraceServiceRequest(resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])])
    copy=ExportTraceServiceRequest.FromString(request.SerializeToString())
    require(copy.resource_spans[0].scope_spans[0].spans[0].name=='local-operation','OTLP trace request roundtrip differs')
    require(copy.resource_spans[0].scope_spans[0].spans[0].trace_id==b'1'*16,'OTLP trace ID bytes differ')
    raises(DecodeError,lambda:ExportTraceServiceRequest.FromString(b'\x80'),'Malformed OTLP protobuf was accepted')
    return ['actual-otlp-trace-message','nested-wire-roundtrip','trace-id-bytes','malformed-wire-data']


def semconv_probe(m,work):
    from opentelemetry.semconv.attributes.http_attributes import HTTP_REQUEST_METHOD,HTTP_RESPONSE_STATUS_CODE
    from opentelemetry.semconv.attributes.service_attributes import SERVICE_NAME
    from opentelemetry.semconv.schemas import Schemas
    from opentelemetry.baggage import set_baggage,get_all
    context=set_baggage(SERVICE_NAME,'cpg-local')
    context=set_baggage(HTTP_REQUEST_METHOD,'GET',context=context)
    context=set_baggage(HTTP_RESPONSE_STATUS_CODE,200,context=context)
    require(dict(get_all(context))=={'service.name':'cpg-local','http.request.method':'GET','http.response.status_code':200},'Semantic attribute/API context mapping differs')
    require(Schemas('https://opentelemetry.io/schemas/1.44.0') is Schemas.V1_44_0,'Schema vocabulary lookup differs')
    raises(ValueError,lambda:Schemas('urn:cpg:unknown-schema'),'Unknown schema enumeration was accepted')
    return ['semantic-attribute-identities','actual-api-context-consumption','schema-version-enumeration','unknown-schema']


def pydantic_core_probe(m,work):
    schema=m.core_schema.typed_dict_schema({'count':m.core_schema.typed_dict_field(m.core_schema.int_schema(gt=0)),
                                          'name':m.core_schema.typed_dict_field(m.core_schema.str_schema(min_length=1))})
    validator=m.SchemaValidator(schema);serializer=m.SchemaSerializer(schema)
    require(validator.validate_python({'count':'3','name':'cpg'})=={'count':3,'name':'cpg'},'Typed dictionary coercion differs')
    require(validator.validate_json(b'{"count":2,"name":"x"}')=={'count':2,'name':'x'},'Native JSON validation differs')
    require(json.loads(serializer.to_json({'count':2,'name':'x'}))=={'count':2,'name':'x'},'Native JSON serialization differs')
    raises(m.ValidationError,lambda:validator.validate_python({'count':0,'name':''}),'Invalid constrained fields were accepted')
    raises(ValueError,lambda:m.from_json(b'{broken'),'Malformed JSON was accepted')
    return ['native-schema-validation','coercion','json-validation','json-serialization','constraint-errors','malformed-json']


def run_pytest(work,source,plugin,extra=(),expected=0):
    fixture=work/'test_local_contract.py';fixture.write_text(textwrap.dedent(source))
    env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1')
    command=[sys.executable,'-I','-B','-m','pytest','-q','-p',plugin,*extra,str(fixture)]
    result=subprocess.run(command,capture_output=True,text=True,cwd=work,env=env,timeout=40)
    require(result.returncode==expected,'Actual pytest plugin run differs: '+result.stdout+'\n'+result.stderr)
    return result.stdout


def pytest_mock_probe(m,work):
    result=run_pytest(work,'''
    import os,pytest
    def test_patch(mocker):
        replacement=mocker.patch('os.getcwd',return_value='cpg')
        assert os.getcwd()=='cpg'
        replacement.assert_called_once_with()
        with pytest.raises(AssertionError):replacement.assert_called_once_with('wrong')
    ''','pytest_mock.plugin')
    require('1 passed' in result,'Mock fixture test was not collected')
    return ['actual-pytest-plugin','mock-fixture-patch','call-assertion','wrong-call-assertion']


def pytest_subprocess_probe(m,work):
    result=run_pytest(work,'''
    import subprocess,pytest
    def test_process(fake_process):
        fake_process.register(['cpg-test-command'],stdout='recorded\\n')
        result=subprocess.run(['cpg-test-command'],capture_output=True,text=True,check=True)
        assert result.stdout=='recorded\\n'
        with pytest.raises(fake_process.exceptions.ProcessNotRegisteredError):subprocess.run(['unregistered-cpg-command'])
    ''','pytest_subprocess')
    require('1 passed' in result,'Fake-process fixture was not collected')
    return ['actual-pytest-plugin','registered-process-response','unknown-process-rejection']


def pytest_timeout_probe(m,work):
    result=run_pytest(work,'''
    import pytest,time
    @pytest.mark.timeout(0.1)
    def test_timeout():time.sleep(2)
    ''','pytest_timeout',['--timeout-method=signal'],expected=1)
    require('Timeout' in result and '1 failed' in result,'Configured test timeout was not enforced')
    return ['actual-pytest-plugin','real-bounded-timeout','expected-failed-test-report']


def pytest_xdist_probe(m,work):
    result=run_pytest(work,'''
    import os,pytest
    @pytest.mark.parametrize('number',range(4))
    def test_worker(number):
        assert os.environ['PYTEST_XDIST_WORKER'].startswith('gw')
        assert number*number>=0
    ''','xdist.plugin',['-n','2'])
    require('4 passed' in result,'Distributed workers did not execute all tests')
    return ['actual-xdist-plugin','two-worker-processes','worker-identity','four-test-results']


def pytest_benchmark_probe(m,work):
    result=run_pytest(work,'''
    def test_bounded_benchmark(benchmark):
        result=benchmark.pedantic(lambda:sum([1,2,3]),rounds=2,iterations=1,warmup_rounds=0)
        assert result==6
    ''','pytest_benchmark.plugin',['--benchmark-min-rounds=1','--benchmark-disable-gc'])
    require('1 passed' in result,'Bounded benchmark fixture did not execute')
    return {'checks':['actual-benchmark-fixture','two-bounded-rounds','return-value'],
            'scope':'Functional benchmark fixture execution only; timing values are not comparative performance or official benchmark qualification.'}


def python_discovery_probe(m,work):
    info=m.PythonInfo.from_exe(sys.executable)
    require(info is not None and info.version_info.major==sys.version_info.major and info.version_info.minor==sys.version_info.minor,'Actual interpreter inspection differs')
    restored=m.PythonInfo.from_json(info.to_json())
    require(restored.version_str==info.version_str and restored.executable==info.executable,'Interpreter metadata JSON roundtrip differs')
    matched=m.get_interpreter(sys.executable)
    require(matched is not None and matched.version_str==info.version_str,'Exact interpreter discovery failed')
    missing=m.get_interpreter(str(work/'missing-python-cpg'))
    require(missing is None,'Missing explicit interpreter was accepted')
    require(m.normalize_isa('amd64')=='x86_64','ISA normalization differs')
    return ['actual-interpreter-child-query','exact-executable-discovery','metadata-roundtrip','missing-interpreter','isa-normalization']


def terminado_probe(m,work):
    import select
    from terminado.management import PtyWithClients
    term=PtyWithClients([sys.executable,'-I','-u','-c','print("READY",flush=True); text=input(); print("VALUE="+text.upper(),flush=True)'],cwd=str(work))
    try:
        output='';deadline=time.monotonic()+3
        while 'READY' not in output and time.monotonic()<deadline:
            if select.select([term.ptyproc.fd],[],[],0.2)[0]:output+=term.ptyproc.read(1024)
        require('READY' in output,'Terminado PTY child did not produce prompt')
        term.ptyproc.write('cpg\n');output='';deadline=time.monotonic()+3
        while 'VALUE=CPG' not in output and time.monotonic()<deadline:
            if select.select([term.ptyproc.fd],[],[],0.2)[0]:output+=term.ptyproc.read(1024)
        require('VALUE=CPG' in output,'Terminado PTY exchange differs')
    finally:term.ptyproc.close(force=True)
    raises(FileNotFoundError,lambda:PtyWithClients([str(work/'missing-command')]),'Missing terminal program was accepted')
    return {'checks':['actual-terminal-process','pty-prompt','input-output-exchange','process-close','missing-command'],
            'scope':'Local PTY management only; browser WebSocket rendering and remote server integration not exercised.'}


def fonttools_probe(m,work):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont,TTLibError
    order=['.notdef','A'];glyphs={}
    for name in order:
        pen=TTGlyphPen(None)
        if name=='A':pen.moveTo((0,0));pen.lineTo((300,700));pen.lineTo((600,0));pen.closePath()
        glyphs[name]=pen.glyph()
    builder=FontBuilder(1000,isTTF=True);builder.setupGlyphOrder(order);builder.setupCharacterMap({65:'A'})
    builder.setupGlyf(glyphs);builder.setupHorizontalMetrics({name:(600,0) for name in order});builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupNameTable({'familyName':'CPGLocal','styleName':'Regular'});builder.setupPost();builder.setupMaxp()
    target=work/'local.ttf';builder.save(target)
    with TTFont(target) as font:
        require(font.getBestCmap()[65]=='A' and font['glyf']['A'].numberOfContours==1,'TrueType binary glyph roundtrip differs')
        xml=io.StringIO();font.saveXML(xml,tables=['cmap']);require('0x41' in xml.getvalue(),'Font table XML serialization differs')
    raises(TTLibError,lambda:TTFont(io.BytesIO(b'not a font')),'Malformed font was accepted')
    return ['actual-truetype-build','glyph-outline','character-map','binary-font-read','table-xml','malformed-font']


def zmq_probe(m,work):
    context=m.Context();sender=context.socket(m.PAIR);receiver=context.socket(m.PAIR)
    try:
        sender.bind('inproc://cpg-local');receiver.connect('inproc://cpg-local')
        sender.send_multipart([b'one',b'two']);require(receiver.poll(1000)&m.POLLIN,'In-process ZeroMQ message did not arrive')
        require(receiver.recv_multipart()==[b'one',b'two'],'Multipart ZeroMQ message differs')
        receiver.send_json({'value':17});require(sender.poll(1000)&m.POLLIN and sender.recv_json()=={'value':17},'ZeroMQ JSON response differs')
        raises(m.Again,lambda:receiver.recv(flags=m.NOBLOCK),'Empty nonblocking socket did not reject receive')
    finally:sender.close(linger=0);receiver.close(linger=0);context.term()
    return ['real-inproc-zmq-transport','multipart-message','json-roundtrip','nonblocking-empty-receive','socket-context-close']


def debugpy_probe(m,work):
    import socket
    probe=socket.socket();probe.bind(('127.0.0.1',0));port=probe.getsockname()[1];probe.close()
    with (work/'adapter.stderr').open('wb') as errorlog:
        process=subprocess.Popen([sys.executable,'-I','-B','-m','debugpy.adapter','--host','127.0.0.1','--port',str(port)],stdout=subprocess.DEVNULL,stderr=errorlog)
        client=None
        try:
            for _ in range(60):
                try:client=socket.create_connection(('127.0.0.1',port),timeout=0.2);break
                except OSError:
                    require(process.poll() is None,'Debug adapter exited during startup');time.sleep(0.05)
            require(client is not None,'Debug adapter did not listen locally');client.settimeout(3);stream=client.makefile('rwb')
            def request(seq,command,arguments):
                raw=json.dumps({'seq':seq,'type':'request','command':command,'arguments':arguments}).encode()
                stream.write(b'Content-Length: '+str(len(raw)).encode()+b'\r\n\r\n'+raw);stream.flush()
                for _ in range(20):
                    headers={}
                    while True:
                        line=stream.readline()
                        require(bool(line),'Debug adapter closed unexpectedly')
                        if line==b'\r\n':break
                        key,value=line.decode().split(':',1);headers[key.lower()]=value.strip()
                    message=json.loads(stream.read(int(headers['content-length'])))
                    if message.get('type')=='response' and message.get('request_seq')==seq:return message
                raise AssertionError('Debug adapter response was not received')
            initialized=request(1,'initialize',{'adapterID':'debugpy','clientID':'cpg-local','linesStartAt1':True,'columnsStartAt1':True})
            require(initialized['success'] and initialized['body'].get('supportsConfigurationDoneRequest'),'Real DAP initialize/capabilities differs')
            unsupported=request(2,'cpgUnsupportedRequest',{})
            require(unsupported['success'] is False,'Unknown DAP command was accepted')
            request(3,'disconnect',{'terminateDebuggee':False});stream.close();client.close();client=None
        finally:
            if client is not None:client.close()
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return {'checks':['real-local-debug-adapter','dap-initialize','capability-negotiation','unsupported-request','disconnect','adapter-process-cleanup'],
            'scope':'Local debug-adapter protocol initialization; breakpoint stepping, attached application debugging, remote processes and IDE integration not qualified.'}


def send2trash_probe(m,work):
    code='''from pathlib import Path\nimport os,sys\nfrom send2trash import send2trash\nwork=Path(sys.argv[1]); target=work/'disposable.txt';target.write_text('retained local trash data')\nsend2trash(str(target));assert not target.exists()\ntrash=Path(os.environ['XDG_DATA_HOME'])/'Trash'\nfiles=list((trash/'files').glob('*'));assert len(files)==1 and files[0].read_text()=='retained local trash data'\ninfos=list((trash/'info').glob('*.trashinfo'));assert len(infos)==1 and '[Trash Info]' in infos[0].read_text()\ntry:send2trash(str(work/'missing-cpg-file'))\nexcept FileNotFoundError:pass\nelse:raise AssertionError('missing trash input accepted')\nprint('passed')\n'''
    env=dict(os.environ,XDG_DATA_HOME=str(work/'xdg-data'))
    result=subprocess.run([sys.executable,'-I','-B','-c',code,str(work)],env=env,capture_output=True,text=True,timeout=10)
    require(result.returncode==0 and result.stdout.strip()=='passed','Private trash move failed: '+result.stdout+result.stderr)
    return ['actual-private-trash-move','retained-file-bytes','trashinfo-metadata','missing-file-rejection']


PROBES={'alive-progress':alive_probe,'argon2-cffi':argon2_probe,'argon2-cffi-bindings':argon2_bindings_probe,
        'build':build_probe,'httpcore2':base.httpcore_probe,'googleapis-common-protos':google_protos_probe,
        'grpcio':grpc_probe,'isoduration':isoduration_probe,'cryptography':cryptography_probe,'ml-dtypes':ml_dtypes_probe,
        'opentelemetry-exporter-http-transport':otel_http_probe,'opentelemetry-exporter-otlp-common':otel_common_probe,
        'opentelemetry-exporter-otlp-proto-common':otel_proto_common_probe,'opentelemetry-proto':otel_proto_probe,
        'opentelemetry-semantic-conventions':semconv_probe,'pydantic-core':pydantic_core_probe,
        'pytest-mock':pytest_mock_probe,'pytest-subprocess':pytest_subprocess_probe,'pytest-timeout':pytest_timeout_probe,
        'pytest-xdist':pytest_xdist_probe,'pytest-benchmark':pytest_benchmark_probe,'python-discovery':python_discovery_probe,
        'terminado':terminado_probe,'fonttools':fonttools_probe,'pyzmq':zmq_probe,'debugpy':debugpy_probe,'send2trash':send2trash_probe}
base.PROBES.update(PROBES)
main=base.main
