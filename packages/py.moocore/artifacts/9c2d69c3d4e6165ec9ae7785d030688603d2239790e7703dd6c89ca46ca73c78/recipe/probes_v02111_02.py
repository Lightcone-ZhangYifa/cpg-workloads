"""Bounded actual local APIs for exact original 0.21.11 candidate resources."""
from pathlib import Path
import asyncio, io, json, logging, math, uuid
from profile_probes import main, PROBES, require, raises, local_module

def aiohttp_probe(m, work):
    from aiohttp import web
    async def run():
        app=web.Application()
        async def ping(request): return web.json_response({'value':17,'query':request.query.get('q')})
        async def echo(request): return web.json_response({'echo':await request.json()},status=201)
        async def failure(request): raise web.HTTPConflict(text='cpg-conflict')
        app.router.add_get('/ping',ping);app.router.add_post('/echo',echo);app.router.add_get('/failure',failure)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1];base='http://127.0.0.1:'+str(port)
        session=m.ClientSession(timeout=m.ClientTimeout(total=5))
        try:
            async with session.get(base+'/ping',params={'q':'a b'}) as response:
                require(response.status==200 and await response.json()=={'value':17,'query':'a b'},'GET JSON/query roundtrip differs')
            async with session.post(base+'/echo',json={'values':[2,3,5]}) as response:
                require(response.status==201 and (await response.json())['echo']['values']==[2,3,5],'POST JSON differs')
            async with session.get(base+'/failure') as response:
                require(response.status==409,'Server failure status differs')
                raises(m.ClientResponseError,response.raise_for_status,'HTTP failure did not raise')
            async with session.get(base+'/missing') as response:require(response.status==404,'Missing route accepted')
        finally:
            await session.close();await runner.cleanup()
        require(session.closed,'HTTP client did not close')
        try: await session.get(base+'/ping')
        except RuntimeError:pass
        else:raise AssertionError('Closed HTTP client accepted request')
    asyncio.run(run());return ['loopback-server','GET-query-JSON','POST-JSON','HTTP-409-error','missing-route-404','client-and-server-close','closed-client-rejection']

def patsy_probe(m,work):
    import numpy as np
    data={'x':[0.,1.,2.,3.],'g':['a','b','a','b']}
    matrix=m.dmatrix('1 + x + C(g)',data)
    require(matrix.shape==(4,3),'Formula shape differs');require(np.allclose(matrix,[[1,0,0],[1,1,1],[1,0,2],[1,1,3]]),'Formula design values differ')
    later=m.build_design_matrices([matrix.design_info],{'x':[4.,5.],'g':['a','b']})[0]
    require(np.allclose(later,[[1,0,4],[1,1,5]]),'Design-info reuse differs')
    raises(m.PatsyError,lambda:m.dmatrix('missing + x',data),'Missing factor accepted')
    raises(m.PatsyError,lambda:m.build_design_matrices([matrix.design_info],{'x':[1.],'g':['c']}),'Unknown categorical level accepted')
    return ['numeric-categorical-design','exact-matrix-values','reuse-design-info','missing-factor-rejection','unknown-category-rejection']

def moocore_probe(m,work):
    import numpy as np
    points=np.array([[1.,3.],[2.,2.],[3.,1.],[3.,3.]])
    require(m.is_nondominated(points).tolist()==[True,True,True,False],'Pareto dominance differs')
    require(np.array_equal(m.filter_dominated(points),points[:3]),'Dominance filtering differs')
    require(abs(m.hypervolume(points,ref=[4.,4.])-6.)<1e-12,'Exact 2D hypervolume differs')
    require(abs(m.epsilon_additive(points[:3],ref=points[:3]))<1e-12,'Reference-set epsilon differs')
    require(np.allclose(m.normalise(points),[[0,1],[.5,.5],[1,0],[1,1]]),'Coordinate normalisation differs')
    require(abs(m.hypervolume(points,ref=[4.])-6.)<1e-12,'Scalar reference broadcasting differs')
    raises(ValueError,lambda:m.hypervolume(points,ref=[4.,4.,4.]),'Wrong reference dimensions accepted')
    return ['Pareto-dominance','nondominated-filter','exact-hypervolume-6','self-epsilon-zero','coordinate-normalisation','scalar-reference-broadcast','reference-dimension-rejection']

def directsearch_probe(m,work):
    import numpy as np
    f=lambda x:float(np.sum((np.asarray(x)-np.array([.25,-.5]))**2))
    result=m.solve_directsearch(f,np.array([2.,-3.]),maxevals=200,alpha0=.5,alpha_min=1e-5,verbose=False)
    require(result.f<.005 and abs(result.f-f(result.x))<1e-12,'Direct-search objective failed to converge consistently')
    require(0<result.nf<=205 and 'directsearch results' in str(result),'Bounded search accounting differs')
    def broken(x):raise RuntimeError('cpg-objective-failure')
    raises(RuntimeError,lambda:m.solve_directsearch(broken,np.array([1.,2.]),maxevals=10,verbose=False),'Objective error was swallowed')
    return ['bounded-derivative-free-minimisation','objective-result-consistency','evaluation-budget','result-format','objective-error-propagation']

def bayesian_probe(m,work):
    bo=m.BayesianOptimization(f=lambda x:1-(x-.25)**2,pbounds={'x':(-2.,2.)},random_state=7,verbose=0)
    bo.register({'x':0.},.9375);bo.maximize(init_points=2,n_iter=2)
    require(len(bo.res)==5,'Bayesian observation count differs')
    require(bo.max['target']>=.9375 and all(-2<=x['params']['x']<=2 for x in bo.res),'Bayesian result/bounds differ')
    require(all(abs(x['target']-(1-(x['params']['x']-.25)**2))<1e-10 for x in bo.res),'Stored observations differ from objective')
    raises(ValueError,lambda:bo.register({'wrong':1.},0.),'Invalid parameter names accepted')
    return ['seeded-GP-optimisation','five-actual-observations','parameter-bounds','objective-consistency','invalid-parameter-rejection']

def formulaic_probe(m,work):
    import numpy as np,pandas as pd
    from formulaic.errors import FactorEvaluationError
    data=pd.DataFrame({'y':[1.,3.,5.,7.],'x':[0.,1.,2.,3.],'g':['a','b','a','b']})
    matrices=m.model_matrix('y ~ x + C(g)',data)
    require(matrices.lhs.shape==(4,1) and matrices.rhs.shape==(4,3),'Model matrix shapes differ')
    require(np.allclose(matrices.lhs['y'],data['y']) and np.allclose(matrices.rhs['x'],data['x']),'Model matrix values differ')
    regenerated=matrices.rhs.model_spec.get_model_matrix(pd.DataFrame({'x':[4.,5.],'g':['a','b']}))
    require(regenerated.shape==(2,3) and np.allclose(regenerated['x'],[4,5]),'Frozen formula spec reuse differs')
    raises(FactorEvaluationError,lambda:m.model_matrix('unknown + x',data),'Missing formula variable accepted')
    return ['response-predictor-matrices','categorical-encoding','exact-numeric-values','model-spec-reuse','missing-variable-rejection']

def skopt_probe(m,work):
    result=m.gp_minimize(lambda x:(x[0]-.2)**2,[(-1.,1.)],n_calls=12,n_initial_points=4,random_state=5)
    require(len(result.func_vals)==12 and float(result.fun)<.1,'Seeded GP minimisation differs')
    require(abs(float(result.fun)-(result.x[0]-.2)**2)<1e-10,'Best objective differs')
    path=work/'optimisation.pkl';m.dump(result,path,store_objective=False);loaded=m.load(path)
    require(loaded.x==result.x and float(loaded.fun)==float(result.fun),'Optimisation serialisation differs')
    raises(ValueError,lambda:m.space.Real(2.,-1.),'Reversed search interval accepted')
    return ['seeded-GP-minimisation','twelve-bounded-evaluations','best-objective-consistency','dump-load-roundtrip','reversed-bounds-rejection']

def optuna_probe(m,work):
    m.logging.set_verbosity(m.logging.WARNING)
    uri='sqlite:///'+str(work/'study.sqlite3')
    study=m.create_study(study_name='cpg-local',storage=uri,direction='minimize',sampler=m.samplers.GridSampler({'x':[-1.,0.,1.,2.]},seed=3))
    study.optimize(lambda trial:(trial.suggest_float('x',-1.,2.)-1.)**2,n_trials=4)
    require(study.best_value==0. and study.best_params=={'x':1.},'Deterministic grid optimum differs')
    loaded=m.load_study(study_name='cpg-local',storage=uri)
    require(len(loaded.trials)==4 and loaded.best_value==0.,'SQLite study reload differs')
    raises(ValueError,lambda:m.create_study(direction='sideways'),'Invalid study direction accepted')
    trial=loaded.ask();raises(ValueError,lambda:trial.suggest_float('bad',2.,1.),'Invalid trial bounds accepted');loaded.tell(trial,state=m.trial.TrialState.FAIL)
    require(loaded.trials[-1].state==m.trial.TrialState.FAIL,'Failed trial lifecycle differs')
    return ['SQLite-study-create','four-grid-trials','exact-optimum','persisted-study-reload','invalid-direction','invalid-bounds','failed-trial-lifecycle']

def nbformat_probe(m,work):
    from jsonschema.exceptions import ValidationError
    book=m.v4.new_notebook(cells=[m.v4.new_markdown_cell('# CPG'),m.v4.new_code_cell('print(2 + 3)',execution_count=1,outputs=[m.v4.new_output('stream',name='stdout',text='5\n')])])
    m.validate(book);path=work/'probe.ipynb';m.write(book,path);again=m.read(path,as_version=4);m.validate(again)
    require(again.cells[1].source=='print(2 + 3)' and again.cells[1].outputs[0].text=='5\n','Notebook IO lost cell/output')
    text=m.writes(again);require(m.reads(text,as_version=4)==again,'Notebook text roundtrip differs')
    bad=m.from_dict(json.loads(text));bad.cells[0]['cell_type']='invalid-kind'
    raises(ValidationError,lambda:m.validate(bad),'Invalid notebook schema accepted')
    return ['notebook-v4-create','code-markdown-output-schema','file-read-write','text-roundtrip','invalid-cell-schema-rejection']

def events_probe(m,work):
    from jsonschema.exceptions import ValidationError
    output=io.StringIO();handler=logging.StreamHandler(output);logger=m.EventLogger(handlers=[handler])
    schema={'$id':'https://cpg.invalid/events/local','version':'1','title':'CPG local event','description':'Bounded local event schema','type':'object','properties':{'value':{'type':'integer','description':'Integer payload'}},'required':['value'],'additionalProperties':False}
    logger.register_event_schema(schema);event=logger.emit(schema_id=schema['$id'],data={'value':17});handler.flush()
    require(event['value']==17 and event['__schema__']==schema['$id'],'Event capsule differs')
    parsed=json.loads(output.getvalue());require(parsed['value']==17 and parsed['__schema_version__']=='1','Structured event output differs')
    raises(ValidationError,lambda:logger.emit(schema_id=schema['$id'],data={'value':'bad'}),'Invalid event accepted')
    logger.remove_handler(handler);require(logger.emit(schema_id=schema['$id'],data={'value':19}) is None,'Removed event handler still active')
    handler.close();return ['schema-register','validated-event-emission','JSON-handler-output','invalid-event-rejection','handler-removal']

def jupyter_client_probe(m,work):
    import zmq
    from jupyter_client.session import Session
    sender=Session(key=b'cpg-local-key');receiver=Session(key=b'cpg-local-key');context=zmq.Context()
    a=context.socket(zmq.PAIR);b=context.socket(zmq.PAIR);a.setsockopt(zmq.LINGER,0);b.setsockopt(zmq.LINGER,0);b.setsockopt(zmq.RCVTIMEO,2000)
    address='inproc://cpg-'+uuid.uuid4().hex;a.bind(address);b.connect(address)
    try:
        sent=sender.send(a,'execute_request',content={'code':'2 + 3','silent':False})
        identities,received=receiver.recv(b,mode=0)
        require(received['content']==sent['content'] and received['header']['msg_id']==sent['header']['msg_id'],'Signed Jupyter message transfer differs')
        message=sender.msg('kernel_info_request',content={'probe':17});frames=sender.serialize(message)
        valid=Session(key=b'cpg-local-key').deserialize(frames[1:]);require(valid['content']=={'probe':17},'Protocol deserialisation differs')
        bad=list(frames[1:]);bad[-1]=b'{"probe":18}'
        raises(ValueError,lambda:Session(key=b'cpg-local-key').deserialize(bad),'Tampered HMAC message accepted')
        raises(ValueError,lambda:Session(key=b'wrong-key').deserialize(frames[1:]),'Wrong HMAC key accepted')
    finally:a.close();b.close();context.term()
    require(context.closed,'ZMQ context did not close')
    return ['in-process-ZMQ-transport','signed-Jupyter-message','header-content-roundtrip','protocol-serialisation','tampered-HMAC-rejection','wrong-key-rejection','context-close']

PROBES.update({'aiohttp':aiohttp_probe,'patsy':patsy_probe,'moocore':moocore_probe,'directsearch':directsearch_probe,'bayesian-optimization':bayesian_probe,'formulaic':formulaic_probe,'scikit-optimize':skopt_probe,'optuna':optuna_probe,'nbformat':nbformat_probe,'jupyter-events':events_probe,'jupyter-client':jupyter_client_probe})
