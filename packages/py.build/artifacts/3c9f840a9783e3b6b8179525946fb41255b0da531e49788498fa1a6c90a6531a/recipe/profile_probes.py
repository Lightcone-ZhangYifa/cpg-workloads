"""Bounded local API contracts for original CPG Python resources, 0.21.10.

Every function performs package operations and verifies explicit results and
failure cases. No remote endpoint, benchmark result, or source-build claim is
made. Installation, integrity, isolation and removal are audited separately.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback


def require(value,message):
    if not value:raise AssertionError(message)


def raises(kind,call,message):
    try:call()
    except kind:return
    raise AssertionError(message)


def local_module(name):
    module=importlib.import_module(name)
    origin=Path(module.__file__).resolve()
    require(origin.is_relative_to(Path(sys.prefix).resolve()),'Imported module escaped the selected prefix: '+name)
    return module


def anyio_probe(m,work):
    async def exercise():
        send,receive=m.create_memory_object_stream(1)
        seen=[]
        async def producer():
            async with send:
                for value in (2,3,5):await send.send(value)
        async with m.create_task_group() as group:
            group.start_soon(producer)
            async with receive:
                async for value in receive:seen.append(value)
        require(seen==[2,3,5],'Task group memory stream changed order or values')
        require(await m.to_thread.run_sync(lambda:sum(seen))==10,'Worker-thread result was lost')
        with m.move_on_after(0) as cancelled:await m.sleep(1)
        require(cancelled.cancel_called,'Deadline cancellation was not requested')
        try:
            with m.fail_after(0):await m.sleep(1)
        except TimeoutError:pass
        else:raise AssertionError('Timeout failed to raise')
        try:await send.send(9)
        except m.ClosedResourceError:pass
        else:raise AssertionError('Closed stream accepted a send')
    m.run(exercise,backend='asyncio')
    return ['task-group','ordered-memory-stream','worker-thread','deadline-cancel','timeout-error','closed-stream']


def asv_runner_probe(m,work):
    from asv_runner.statistics import quantile,compute_stats,binom_pmf
    require(quantile([5,1,3,2,4],0.5)==3,'Benchmark sample median differs')
    require(quantile([0,10],0.25)==2.5,'Interpolated sample quantile differs')
    value,stats=compute_stats([1.,2.,3.,4.,5.],number=10)
    require(value==3. and stats['repeat']==5 and stats['number']==10,'Benchmark statistics or sampling metadata differ')
    require(abs(binom_pmf(2,1,0.5)-0.5)<1e-12,'Binomial probability differs')
    require(compute_stats([],1)==(None,None),'Empty sample behavior differs')
    raises(ValueError,lambda:quantile([1,2],1.1),'Invalid quantile was accepted')
    return ['sample-median','interpolated-quantile','benchmark-sample-statistics','binomial-probability','empty-samples','invalid-quantile']


def jupyterlab_pygments_probe(m,work):
    from pygments import highlight
    from pygments.lexers import PythonLexer
    from pygments.formatters import HtmlFormatter
    rendered=highlight('value = 7\n',PythonLexer(),HtmlFormatter(style=m.JupyterStyle))
    require('value' in rendered and '7' in rendered,'Jupyter style highlighting output differs')
    require(m._jupyter_labextension_paths()[0]['dest']=='jupyterlab_pygments','Lab extension declaration differs')
    return ['real-highlight','jupyter-style','labextension-declaration']


def nest_asyncio_probe(m,work):
    loop=asyncio.new_event_loop()
    async def value():await asyncio.sleep(0);return 17
    async def nested():return loop.run_until_complete(value())
    try:
        m.apply(loop)
        require(loop.run_until_complete(nested())==17,'Reentrant event loop did not return nested result')
        async def failure():raise ValueError('cpg nested failure')
        async def nested_failure():return loop.run_until_complete(failure())
        raises(ValueError,lambda:loop.run_until_complete(nested_failure()),'Nested coroutine exception was lost')
    finally:
        loop.close()
        if hasattr(m,'unapply'):m.unapply()
    require(loop.is_closed(),'Patched event loop was left open')
    return ['actual-nested-loop','coroutine-result','nested-exception','loop-close','patch-reversal']


def aiosignal_probe(m,work):
    events=[];signal=m.Signal('owner')
    async def first(value):events.append(('first',value))
    async def second(value):events.append(('second',value))
    signal.append(first);signal.append(second)
    raises(RuntimeError,lambda:asyncio.run(signal.send(7)),'Unfrozen signal accepted dispatch')
    signal.freeze();asyncio.run(signal.send(7))
    require(events==[('first',7),('second',7)],'Ordered asynchronous callbacks did not execute')
    raises(RuntimeError,lambda:signal.append(first),'Frozen signal accepted mutation')
    return ['unfrozen-dispatch-rejection','frozen-callback-order','callback-arguments','frozen-mutation-rejection']


def multiprocess_probe(m,work):
    offset=7
    with m.get_context('fork').Pool(2) as pool:
        require(pool.map(lambda x:x*x+offset,[1,2,3])==[8,11,16],'Serialized closure pool result differs')
        result=pool.apply_async(lambda:1/0)
        raises(ZeroDivisionError,result.get,'Remote worker exception was not propagated')
    require(not m.active_children(),'Pool context leaked worker processes')
    return ['dill-serialized-closure','real-process-pool','ordered-map','remote-exception','worker-cleanup']


def yarl_probe(m,work):
    url=m.URL('https://example.org/a b').with_query([('x','1'),('x','2')])
    require(url.path=='/a b' and url.query.getall('x')==['1','2'],'URL path/query representation differs')
    require(str(url)=='https://example.org/a%20b?x=1&x=2','URL percent encoding differs')
    require(url.join(m.URL('../next')).path=='/next','Relative URL resolution differs')
    require(m.URL('https://bücher.example/').raw_host=='xn--bcher-kva.example','IDNA host encoding differs')
    raises(ValueError,lambda:m.URL('https://example.org:invalid/').port,'Invalid port was accepted')
    return ['percent-encoding','duplicate-query-values','relative-resolution','unicode-host','invalid-port']


def gitdb_probe(m,work):
    from gitdb.db.mem import MemoryDB
    from gitdb import IStream
    from gitdb.exc import BadObject
    db=MemoryDB();payload=b'compiler-playground exact local blob\n'
    obj=db.store(IStream(b'blob',len(payload),io.BytesIO(payload)))
    expected=hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).digest()
    require(obj.binsha==expected,'Git object content address differs')
    require(db.stream(expected).read()==payload,'Stored Git blob did not roundtrip')
    require(db.info(expected).size==len(payload),'Stored object size differs')
    raises(BadObject,lambda:db.stream(b'\0'*20),'Unknown Git object was accepted')
    return ['actual-object-store','git-content-address','stream-roundtrip','object-size','missing-object']


def gitpython_probe(m,work):
    # Repo operations use the host git executable; the report names it explicitly.
    git=__import__('shutil').which('git')
    require(git is not None,'GitPython repository operations require a git executable')
    repo=m.Repo.init(work/'repository')
    actor=m.Actor('CPG local check','cpg-check@example.invalid')
    path=Path(repo.working_tree_dir)/'sample.txt';path.write_text('first\n')
    repo.index.add(['sample.txt']);first=repo.index.commit('first local commit',author=actor,committer=actor)
    path.write_text('second\n');repo.index.add(['sample.txt'])
    second=repo.index.commit('second local commit',author=actor,committer=actor)
    require(second.parents[0].hexsha==first.hexsha,'Commit parent differs')
    require((first.tree/'sample.txt').data_stream.read()==b'first\n','Historical blob differs')
    require(len(list(repo.iter_commits()))==2,'Commit history count differs')
    raises(m.exc.BadName,lambda:repo.commit('missing-cpg-reference'),'Missing revision was accepted')
    repo.close()
    return {'checks':['local-repository-init','two-real-commits','parent-link','historical-blob','missing-revision','repository-close'],
            'external_local_command':{'path':git,'scope':'Host git command used for local repository operations; no remote or source-build qualification.'}}


def referencing_probe(m,work):
    from referencing.jsonschema import DRAFT202012
    from referencing.exceptions import NoSuchResource,PointerToNowhere
    document={'$schema':'https://json-schema.org/draft/2020-12/schema','$defs':{'value':{'type':'integer','minimum':0}}}
    resource=m.Resource.from_contents(document,default_specification=DRAFT202012)
    registry=m.Registry().with_resource('urn:cpg:schema',resource)
    resolver=registry.resolver('urn:cpg:schema')
    require(resolver.lookup('#/$defs/value').contents=={'type':'integer','minimum':0},'Local JSON Pointer resolution differs')
    require(registry.contents('urn:cpg:schema')==document,'Registry contents differ')
    raises(NoSuchResource,lambda:registry.contents('urn:cpg:missing'),'Missing resource was accepted')
    raises(PointerToNowhere,lambda:resolver.lookup('#/$defs/missing'),'Missing JSON Pointer was accepted')
    return ['immutable-registry','local-resource','json-pointer-resolution','missing-resource','missing-pointer']


def jsonschema_specifications_probe(m,work):
    from referencing.exceptions import NoSuchResource
    schema=m.REGISTRY.contents('https://json-schema.org/draft/2020-12/schema')
    require(schema['$id']=='https://json-schema.org/draft/2020-12/schema','Draft schema identity differs')
    core=m.REGISTRY.resolver('https://json-schema.org/draft/2020-12/schema').lookup('meta/core').contents
    require('$id' in core.get('properties',{}),'Cross-resource core vocabulary resolution failed')
    draft7=m.REGISTRY.contents('http://json-schema.org/draft-07/schema#')
    require(draft7['properties']['type'],'Draft 7 type vocabulary is missing')
    raises(NoSuchResource,lambda:m.REGISTRY.contents('urn:cpg:no-schema'),'Unknown specification was accepted')
    return ['draft2020-schema','cross-resource-core-vocabulary','draft7-schema','unknown-specification']


def httpcore_probe(m,work):
    from http_fixture import local_server
    with local_server() as base,m.ConnectionPool() as pool:
        response=pool.request('GET',base+'/ok')
        require(response.status==200 and 'path' in json.loads(response.content),'HTTP pool GET response differs')
        post=pool.request('POST',base+'/echo',headers={'content-type':'application/json'},content=b'{"probe":true}')
        require(json.loads(post.content)=={'probe':True},'HTTP pool body roundtrip differs')
        missing=pool.request('GET',base+'/error')
        require(missing.status==503,'HTTP status propagation differs')
        raises(m.UnsupportedProtocol,lambda:pool.request('GET','cpg-unknown://example.invalid/'),'Unsupported protocol was accepted')
    return ['real-loopback-get','post-body-roundtrip','status-propagation','unsupported-protocol','pool-close']


def ipython_pygments_probe(m,work):
    from pygments import lex
    from pygments.token import Token
    code='In [1]: value = 2\nOut[1]: 2\n'
    rows=list(lex(code,m.IPythonConsoleLexer()))
    require(''.join(text for _,text in rows)==code,'Console lexing changed source text')
    require(any(kind in Token.Generic.Prompt for kind,_ in rows),'IPython prompts were not identified')
    python_rows=list(lex('x = 1 + 2\n',m.IPython3Lexer()))
    require(any(kind in Token.Literal.Number for kind,_ in python_rows),'Python numbers were not tokenized')
    plain=list(lex('ordinary text\n',m.IPythonConsoleLexer()))
    require(not any(kind in Token.Generic.Prompt for kind,_ in plain),'Ordinary text became an input prompt')
    return ['console-roundtrip','input-output-prompt-tokens','ipython-numeric-tokens','non-prompt-negative']


def jupyter_core_probe(m,work):
    from jupyter_core import paths
    data=work/'jupyter-data';old=os.environ.get('JUPYTER_DATA_DIR')
    os.environ['JUPYTER_DATA_DIR']=str(data)
    try:
        require(Path(paths.jupyter_data_dir())==data,'Jupyter data-dir override differs')
        require(str(data/'kernels') in paths.jupyter_path('kernels'),'Jupyter kernel search path omitted override')
    finally:
        if old is None:os.environ.pop('JUPYTER_DATA_DIR',None)
        else:os.environ['JUPYTER_DATA_DIR']=old
    target=work/'connection.json'
    with paths.secure_write(str(target)) as handle:handle.write('{"local":true}')
    require(target.read_text()=='{"local":true}' and target.stat().st_mode&0o777==0o600,'Secure writer content or permissions differ')
    raises(FileNotFoundError,lambda:paths.secure_write(str(work/'missing-parent'/'file')).__enter__(),'Secure writer accepted a missing parent')
    return ['environment-path-override','kernel-search-path','secure-file-write','0600-permissions','missing-parent']


def mako_probe(m,work):
    from mako.template import Template
    from mako.lookup import TemplateLookup
    from mako.exceptions import SyntaxException,TopLevelLookupException
    template=Template('% for n in values:\n${n*n},\n% endfor\n')
    require(template.render(values=[2,3]).replace('\n','')=='4,9,','Compiled template loop rendering differs')
    require(Template('${text | h}').render(text='<x>')=='&lt;x&gt;','HTML filter did not escape markup')
    (work/'base.txt').write_text('Hello ${name}!')
    lookup=TemplateLookup(directories=[str(work)],strict_undefined=True)
    require(lookup.get_template('base.txt').render(name='CPG')=='Hello CPG!','Filesystem lookup render differs')
    raises(SyntaxException,lambda:Template('% if:\nwrong\n% endif'),'Invalid template syntax was accepted')
    raises(TopLevelLookupException,lambda:lookup.get_template('missing.txt'),'Missing template was accepted')
    return ['compiled-loop','html-escaping','filesystem-template-lookup','invalid-syntax','missing-template']


def matplotlib_inline_probe(m,work):
    from matplotlib_inline.config import InlineBackend
    config=InlineBackend.instance()
    original=set(config.figure_formats)
    try:
        config.figure_formats={'png','svg'}
        require(config.figure_formats=={'png','svg'},'Inline format configuration did not persist')
        raises(__import__('traitlets').TraitError,lambda:setattr(config,'figure_formats',{'not-a-format'}),'Unsupported inline format was accepted')
    finally:config.figure_formats=original
    return ['inline-format-configuration','invalid-format-rejection']


def pexpect_probe(m,work):
    child=m.spawn(sys.executable,['-I','-u','-c','print("READY",flush=True); value=input(); print("RESULT="+value.upper(),flush=True)'],encoding='utf-8',timeout=3)
    try:
        child.expect_exact('READY');child.sendline('cpg');child.expect_exact('RESULT=CPG');child.expect(m.EOF)
        child.close();require(child.exitstatus==0,'PTY child exit differs')
    finally:
        if child.isalive():child.close(force=True)
    sleeper=m.spawn(sys.executable,['-I','-c','import time; time.sleep(2)'],encoding='utf-8',timeout=0.05)
    try:raises(m.TIMEOUT,lambda:sleeper.expect_exact('never-produced'),'Missing output did not time out')
    finally:sleeper.close(force=True)
    require(not sleeper.isalive(),'Timeout child was left alive')
    return ['real-pty-child','expect-prompt','send-input','matched-response','eof-exit','timeout','forced-child-cleanup']


def prompt_toolkit_probe(m,work):
    from prompt_toolkit.document import Document
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import WordCompleter,CompleteEvent
    from prompt_toolkit.formatted_text import FormattedText,to_formatted_text
    from prompt_toolkit.validation import Validator,ValidationError
    document=Document('alpha beta',cursor_position=6)
    require(document.get_word_before_cursor()=='' and document.get_word_under_cursor()=='beta','Cursor word boundaries differ')
    buffer=Buffer();buffer.text='abc';buffer.cursor_position=1;buffer.insert_text('Z')
    require(buffer.text=='aZbc' and buffer.cursor_position==2,'Editable buffer insertion differs')
    words=list(WordCompleter(['apple','apricot','banana']).get_completions(Document('ap'),CompleteEvent()))
    require([x.text for x in words]==['apple','apricot'],'Word completion differs')
    validator=Validator.from_callable(lambda text:text.isdigit(),error_message='digits required')
    validator.validate(Document('123'))
    raises(ValidationError,lambda:validator.validate(Document('abc')),'Invalid buffer text was accepted')
    require(to_formatted_text(FormattedText([('class:title','CPG')]))[0][1]=='CPG','Formatted text conversion differs')
    return ['document-word-boundaries','buffer-edit','word-completion','input-validation','formatted-text']


def wheel_probe(m,work):
    import zipfile
    from wheel.wheelfile import WheelFile
    from wheel.wheelfile import WheelError
    target=work/'cpg_example-1.0-py3-none-any.whl'
    with WheelFile(str(target),'w') as whl:
        whl.writestr('cpg_example/data.txt',b'exact local wheel data\n')
        whl.writestr('cpg_example-1.0.dist-info/METADATA',b'Metadata-Version: 2.1\nName: cpg-example\nVersion: 1.0\n')
        whl.writestr('cpg_example-1.0.dist-info/WHEEL',b'Wheel-Version: 1.0\nGenerator: cpg-check\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
    with WheelFile(str(target)) as whl:
        require(whl.read('cpg_example/data.txt')==b'exact local wheel data\n','Wheel member roundtrip differs')
        record=whl.read('cpg_example-1.0.dist-info/RECORD').decode()
        require('sha256=' in record and 'cpg_example/data.txt' in record,'Wheel RECORD hashes are missing')
    (work/'damaged').mkdir()
    bad=work/'damaged'/target.name
    with zipfile.ZipFile(target) as original,zipfile.ZipFile(bad,'w') as damaged:
        for name in original.namelist():damaged.writestr(name,b'wrong\n' if name=='cpg_example/data.txt' else original.read(name))
    def read_bad():
        with WheelFile(str(bad)) as whl:whl.read('cpg_example/data.txt')
    raises(WheelError,read_bad,'Corrupted wheel member was accepted')
    return ['actual-wheel-write','record-generation','member-roundtrip','corrupt-member-hash-rejection']


def rfc3987_probe(m,work):
    require(m.is_valid_syntax('iri','https://example.org/路径?q=1#part'),'Valid Unicode IRI was rejected')
    require(m.is_valid_syntax('absolute_iri','https://example.org/path'),'Absolute IRI was rejected')
    require(not m.is_valid_syntax('iri','not an iri'),'Invalid IRI with spaces was accepted')
    return ['unicode-iri','absolute-iri','invalid-iri']


def stack_data_probe(m,work):
    script=work/'trace_fixture.py'
    script.write_text('''import json,sys\nfrom stack_data import FrameInfo\ndef sample():\n    value=7\n    try:\n        return value/0\n    except ZeroDivisionError:\n        frame=FrameInfo(sys.exc_info()[2])\n        rendered=[line.render() for line in frame.lines]\n        assert any("value/0" in line for line in rendered),rendered\n        assert frame.executing.code_qualname()=="sample",frame.executing.code_qualname()\n        print(json.dumps({"status":"passed","lines":rendered}))\nsample()\n''')
    result=subprocess.run([sys.executable,'-I','-B',str(script)],capture_output=True,text=True,timeout=10)
    require(result.returncode==0,'Real traceback inspection failed: '+result.stderr)
    require(json.loads(result.stdout)['status']=='passed','Traceback fixture did not pass')
    return ['real-exception-traceback','executing-code-identity','rendered-source-context']


def typing_inspection_probe(m,work):
    import typing
    from typing_inspection.introspection import inspect_annotation,AnnotationSource,get_literal_values,ForbiddenQualifier
    annotation=inspect_annotation(typing.Annotated[int,'cpg'],annotation_source=AnnotationSource.CLASS)
    require(annotation.type is int and annotation.metadata==['cpg'],'Annotated type/metadata inspection differs')
    require(list(get_literal_values(typing.Literal[1,2,1]))==[1,2],'Literal deduplication differs')
    qualified=inspect_annotation(typing.ClassVar[int],annotation_source=AnnotationSource.CLASS)
    require(qualified.type is int and 'class_var' in qualified.qualifiers,'ClassVar qualifier inspection differs')
    raises(ForbiddenQualifier,lambda:inspect_annotation(typing.ClassVar[int],annotation_source=AnnotationSource.FUNCTION),'Forbidden qualifier was accepted')
    return ['annotated-type','annotation-metadata','literal-values','classvar-qualifier','forbidden-qualifier']


def werkzeug_probe(m,work):
    from werkzeug.wrappers import Request,Response
    from werkzeug.test import Client
    from werkzeug.routing import Map,Rule
    from werkzeug.exceptions import NotFound,MethodNotAllowed
    routes=Map([Rule('/items/<int:item>',endpoint='item',methods=['GET'])])
    adapter=routes.bind('localhost')
    require(adapter.match('/items/7')==('item',{'item':7}),'Route conversion differs')
    require(adapter.build('item',{'item':9})=='/items/9','Route generation differs')
    raises(NotFound,lambda:adapter.match('/missing'),'Unknown route was accepted')
    raises(MethodNotAllowed,lambda:adapter.match('/items/7',method='POST'),'Unsupported HTTP method was accepted')
    @Request.application
    def app(request):return Response(json.dumps({'query':request.args.get('q'),'method':request.method}),mimetype='application/json')
    client=Client(app,Response)
    response=client.get('/?q=CPG')
    require(response.status_code==200 and response.json=={'query':'CPG','method':'GET'},'WSGI request/response differs')
    return ['route-parse','route-build','missing-route','method-rejection','actual-wsgi-request-response']


PROBES={'asv-runner':asv_runner_probe,'jupyterlab-pygments':jupyterlab_pygments_probe,'nest-asyncio2':nest_asyncio_probe,
        'anyio':anyio_probe,'aiosignal':aiosignal_probe,'multiprocess':multiprocess_probe,
        'yarl':yarl_probe,'gitdb':gitdb_probe,'gitpython':gitpython_probe,'referencing':referencing_probe,
        'jsonschema-specifications':jsonschema_specifications_probe,'httpcore':httpcore_probe,
        'ipython-pygments-lexers':ipython_pygments_probe,'jupyter-core':jupyter_core_probe,
        'mako':mako_probe,'matplotlib-inline':matplotlib_inline_probe,'pexpect':pexpect_probe,
        'prompt-toolkit':prompt_toolkit_probe,'wheel':wheel_probe,'rfc3987-syntax':rfc3987_probe,
        'stack-data':stack_data_probe,'typing-inspection':typing_inspection_probe,'werkzeug':werkzeug_probe}


def main(resource,distribution,module):
    parser=argparse.ArgumentParser();parser.add_argument('--expected-version',required=True);parser.add_argument('--version-only',action='store_true')
    args=parser.parse_args(); result={'resource_id':resource,'distribution':distribution,'status':'failed'}
    try:
        actual=importlib.metadata.version(distribution)
        require(actual==args.expected_version,'Exact installed distribution version differs: '+actual)
        result['version']=actual
        if not args.version_only:
            mod=local_module(module)
            with tempfile.TemporaryDirectory(prefix='cpg-functional-',dir=Path.cwd()) as temporary:
                result['operations']=PROBES[distribution.lower().replace('_','-')](mod,Path(temporary))
            result['module_file']=str(Path(mod.__file__).resolve())
        result['status']='passed'
    except BaseException as error:
        result.update(error=repr(error),traceback=traceback.format_exc())
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1
