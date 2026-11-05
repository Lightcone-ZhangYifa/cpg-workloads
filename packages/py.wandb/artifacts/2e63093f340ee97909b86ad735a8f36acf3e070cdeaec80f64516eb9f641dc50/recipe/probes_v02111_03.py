"""Exact-wheel local data, plotting, optimisation, telemetry and kernel probes."""
from pathlib import Path
import hashlib,io,json,os,sys,time
from profile_probes import main,PROBES,require,raises,local_module

def file_result(path):return {'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def arrow_probe(m,work):
    import pyarrow.compute as pc,pyarrow.parquet as pq
    table=m.table({'id':[1,2,3,4],'label':['a','b','c','d'],'value':[1.5,None,2.5,3.5]})
    require(table.num_rows==4 and table['value'].null_count==1,'Arrow table/null semantics differ')
    require(pc.sum(table['value']).as_py()==7.5,'Arrow aggregation differs')
    filtered=table.filter(pc.greater(table['id'],m.scalar(2)));require(filtered['id'].to_pylist()==[3,4],'Arrow filter differs')
    path=work/'table.arrow'
    with m.OSFile(str(path),'wb') as output:
        with m.ipc.new_file(output,table.schema) as writer:writer.write_table(table)
    with m.memory_map(str(path),'r') as source:require(m.ipc.open_file(source).read_all().equals(table),'IPC file roundtrip differs')
    parquet=work/'table.parquet';pq.write_table(table,parquet,row_group_size=2);require(pq.read_table(parquet).equals(table),'Parquet roundtrip differs')
    raises(m.ArrowInvalid,lambda:m.array(['not-integer'],type=m.int64()),'Invalid integer conversion accepted')
    raises(m.ArrowInvalid,lambda:m.ipc.open_file(m.BufferReader(b'broken IPC')),'Invalid IPC accepted')
    return ['nullable-typed-table','compute-sum-filter','IPC-file-memory-map','Parquet-two-row-groups','invalid-conversion','invalid-IPC',file_result(parquet)]

def matplotlib_probe(m,work):
    m.use('Agg',force=True)
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from PIL import Image
    figure=Figure(figsize=(3,2),dpi=60);canvas=FigureCanvasAgg(figure);axis=figure.subplots();line=axis.plot([0,1,2],[0,1,4],label='squares')[0];axis.set_title('CPG local render');axis.legend()
    require(list(line.get_ydata())==[0,1,4],'Line data differs');path=work/'plot.png';canvas.print_png(str(path))
    with Image.open(path) as im:require(im.size==(180,120) and im.mode=='RGBA' and len(set(im.getdata()))>10,'Agg rendering dimensions/pixels differ')
    require(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'),'PNG encoding differs')
    raises(ValueError,lambda:axis.plot([0,1],[2]),'Mismatched plot dimensions accepted')
    raises(ValueError,lambda:m.colors.to_rgba('not-a-colour'),'Invalid colour accepted');figure.clear()
    return ['headless-Agg-render','line-data','legend-title','PNG-dimensions-and-pixels','invalid-dimensions','invalid-colour','figure-clear',file_result(path)]

def seaborn_probe(m,work):
    import matplotlib;matplotlib.use('Agg',force=True)
    import matplotlib.pyplot as plt
    import pandas as pd
    frame=pd.DataFrame({'x':[0,1,2,3],'y':[0.,1.,4.,9.],'group':['a','a','b','b']})
    figure,axes=plt.subplots(1,2,figsize=(4,2),dpi=60)
    m.scatterplot(data=frame,x='x',y='y',hue='group',ax=axes[0]);m.histplot(data=frame,x='x',bins=4,ax=axes[1])
    require(len(axes[0].collections[0].get_offsets())==4,'Scatter rows differ');require(sum(p.get_height() for p in axes[1].patches)==4,'Histogram counts differ')
    path=work/'seaborn.png';figure.savefig(path);require(path.read_bytes().startswith(b'\x89PNG'),'Seaborn render failed')
    raises(ValueError,lambda:m.color_palette('cpg-no-such-palette'),'Invalid palette accepted');plt.close(figure);require(not plt.fignum_exists(figure.number),'Plot did not close')
    return ['dataframe-scatter-hue','histogram-counts','headless-PNG','invalid-palette','figure-close',file_result(path)]

def statsmodels_probe(m,work):
    import numpy as np,statsmodels.api as sm
    x=np.arange(8,dtype=float);design=sm.add_constant(x);y=1+2*x;fit=sm.OLS(y,design).fit()
    require(np.allclose(fit.params,[1,2],atol=1e-10) and fit.rsquared>.999999,'OLS coefficients/residual fit differ')
    pred=fit.get_prediction([[1,8],[1,9]]);require(np.allclose(pred.predicted_mean,[17,19]),'OLS predictions differ')
    path=work/'fit.pickle';fit.save(path);restored=sm.load(path);require(np.allclose(restored.params,fit.params),'Model save/load differs')
    raises(ValueError,lambda:sm.OLS(y[:-1],design),'Mismatched regression dimensions accepted')
    return ['OLS-fit','exact-linear-coefficients','prediction-results','model-save-load','invalid-dimensions',file_result(path)]

def datasets_probe(m,work):
    m.disable_progress_bars()
    original=m.Dataset.from_dict({'id':[0,1,2,3],'text':['a','bb','ccc','dddd']});mapped=original.map(lambda row:{'length':len(row['text'])},load_from_cache_file=False)
    require(list(mapped['length'])==[1,2,3,4],'Dataset map values differ');selected=mapped.filter(lambda row:row['length']>=3,load_from_cache_file=False);require(list(selected['id'])==[2,3],'Dataset filter differs')
    split=mapped.train_test_split(test_size=2,seed=7);require(len(split['train'])==len(split['test'])==2,'Seeded split sizes differ')
    location=work/'saved-dataset';mapped.save_to_disk(str(location));loaded=m.load_from_disk(str(location));require(loaded.to_dict()==mapped.to_dict(),'Dataset disk persistence differs')
    raises(IndexError,lambda:loaded.select([99]),'Out-of-range row selection accepted');raises(ValueError,lambda:loaded.remove_columns(['missing']),'Missing column removal accepted')
    return ['in-memory-Arrow-dataset','map-derived-column','filter-rows','seeded-train-test-split','save-load-disk','invalid-row','missing-column']

def nevergrad_probe(m,work):
    import numpy as np
    parameter=m.p.Array(init=np.array([2.,-3.])).set_bounds(-5.,5.);parameter.random_state.seed(4)
    optimizer=m.optimizers.OnePlusOne(parametrization=parameter,budget=40,num_workers=1)
    objective=lambda x:float(np.sum((np.asarray(x)-np.array([.5,-.5]))**2))
    recommendation=optimizer.minimize(objective);value=objective(recommendation.value)
    require(np.isfinite(value) and value<8.5,'Derivative-free search failed to improve starting objective')
    require(optimizer.num_ask==40 and optimizer.num_tell==40,'Budget accounting differs')
    require(np.all(recommendation.value>=-5) and np.all(recommendation.value<=5),'Parameter bounds violated')
    raises(ValueError,lambda:m.p.Array(shape=(-1,)),'Invalid parameter dimensions accepted')
    return ['seeded-OnePlusOne-search','forty-actual-ask-tell-evaluations','improved-objective','bounded-parameters','invalid-shape',{'best_objective':value}]

def tensorboard_probe(m,work):
    from tensorboard.summary.writer.event_file_writer import EventFileWriter
    from tensorboard.compat.proto.event_pb2 import Event
    from tensorboard.compat.proto.summary_pb2 import Summary
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    from google.protobuf.message import DecodeError
    logdir=work/'events';writer=EventFileWriter(str(logdir),max_queue_size=1,flush_secs=1)
    try:
        for step,value in [(1,.5),(2,.25)]:writer.add_event(Event(wall_time=float(step),step=step,summary=Summary(value=[Summary.Value(tag='loss',simple_value=value)])))
        writer.flush()
    finally:writer.close()
    reader=EventAccumulator(str(logdir));reader.Reload();values=reader.Scalars('loss');require([(x.step,x.value) for x in values]==[(1,.5),(2,.25)],'TensorBoard event/scalar persistence differs')
    files=list(logdir.glob('events.out.tfevents.*'));require(len(files)==1 and files[0].stat().st_size>0,'Event file missing')
    raises(KeyError,lambda:reader.Scalars('missing-tag'),'Missing scalar tag accepted');raises(DecodeError,lambda:Event.FromString(b'\xff'),'Invalid event protobuf accepted')
    return ['local-event-writer','flush-close','event-accumulator-reload','exact-scalars-and-steps','missing-tag','malformed-protobuf',file_result(files[0])]

def wandb_probe(m,work):
    settings=m.Settings(disable_git=True,save_code=False,x_disable_stats=True,x_disable_meta=True,x_service_wait=20,console='off',silent=True)
    run=m.init(project='cpg-local-probe',mode='offline',dir=str(work),config={'seed':3},settings=settings)
    require(run.settings.mode=='offline' and run.settings.disable_git,'Offline/no-git mode differs')
    run.log({'metric':.5},step=0);run.log({'metric':.25},step=1);run.summary['answer']=42;require(run.summary['answer']==42 and run.config['seed']==3,'Local run metadata differs')
    directory=Path(run.dir).parent;run.finish(exit_code=0);require(m.run is None,'Run did not finish')
    streams=list(directory.glob('run-*.wandb'));require(len(streams)==1 and streams[0].stat().st_size>0,'Offline run stream missing')
    raises(ValueError,lambda:m.Settings(mode='cpg-invalid-mode'),'Invalid SDK mode accepted')
    return ['offline-init-with-private-settings','git-disabled-and-unavailable','two-local-metric-steps','config-summary','finish','offline-record-stream','invalid-mode',file_result(streams[0])]

def nbconvert_probe(m,work):
    import nbformat
    from nbconvert.exporters import HTMLExporter,PythonExporter
    from jinja2.exceptions import TemplateNotFound
    book=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# CPG export'),nbformat.v4.new_code_cell('value = 2 + 3\nprint(value)')])
    html,resources=HTMLExporter(template_name='basic').from_notebook_node(book);require('CPG export' in html and 'value' in html and '<' in html,'HTML export lost content')
    code,_=PythonExporter().from_notebook_node(book);require('value = 2 + 3' in code,'Python export lost code');compile(code,'cpg-export.py','exec')
    path=work/'notebook.html';path.write_text(html);raises(ValueError,lambda:HTMLExporter(template_name='cpg-no-such-template').from_notebook_node(book),'Missing template accepted')
    return ['v4-notebook-to-HTML','code-and-markdown-preserved','Python-export','generated-Python-compilation','missing-template-rejection',file_result(path)]

def ipython_probe(m,work):
    from IPython.core.interactiveshell import InteractiveShell
    shell=InteractiveShell.instance()
    try:
        result=shell.run_cell('cpg_values = [2, 3, 5]\ncpg_total = sum(cpg_values)',store_history=False)
        require(result.success and shell.user_ns['cpg_total']==10,'Interactive execution differs')
        result=shell.run_cell('import sys\ncpg_prefix = sys.prefix',store_history=False);require(result.success and shell.user_ns['cpg_prefix']==sys.prefix,'Interactive interpreter escaped prefix')
        shell.run_cell_magic('capture','cpg_capture','print("captured-local-output")');require(shell.user_ns['cpg_capture'].stdout=='captured-local-output\n','Capture cell magic differs')
        error=shell.run_cell('raise ValueError("cpg-local-error")',store_history=False);require(isinstance(error.error_in_exec,ValueError) and not error.success,'Interactive runtime error lost')
        syntax=shell.run_cell('if :',store_history=False);require(isinstance(syntax.error_before_exec,SyntaxError),'Interactive syntax error lost')
    finally:shell.reset(new_session=False);InteractiveShell.clear_instance()
    return ['interactive-Python-cell','namespace-result','private-interpreter','capture-cell-magic','runtime-error','syntax-error','session-reset']

def ipykernel_probe(m,work):
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    directory=work/'kernels/cpg-private';directory.mkdir(parents=True)
    (directory/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'CPG private','language':'python'}))
    manager=KernelManager(kernel_name='cpg-private',kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(work/'kernels')],ensure_native_kernel=False),connection_file=str(work/'connection.json'))
    client=None
    def execute(code):
        msg_id=client.execute(code);messages=[];deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            msg=client.get_iopub_msg(timeout=10)
            if msg.get('parent_header',{}).get('msg_id')!=msg_id:continue
            messages.append(msg)
            if msg['msg_type']=='status' and msg['content']['execution_state']=='idle':break
        else:raise AssertionError('Kernel never returned idle')
        return messages
    try:
        manager.start_kernel(cwd=str(work));client=manager.client();client.start_channels();client.wait_for_ready(timeout=30)
        messages=execute('import sys\nprint("CPG_PREFIX=" + sys.prefix)\n2 + 3')
        require(any(x['msg_type']=='stream' and 'CPG_PREFIX='+sys.prefix in x['content']['text'] for x in messages),'Kernel interpreter escaped selected prefix')
        require(any(x['msg_type']=='execute_result' and x['content']['data']['text/plain']=='5' for x in messages),'Kernel execution result differs')
        error=execute('raise ValueError("cpg-kernel-error")');require(any(x['msg_type']=='error' and x['content']['ename']=='ValueError' and x['content']['evalue']=='cpg-kernel-error' for x in error),'Kernel error response differs')
    finally:
        if client is not None:client.stop_channels()
        if manager.has_kernel:manager.shutdown_kernel(now=True)
    require(not manager.is_alive(),'Kernel process remained alive after shutdown')
    return ['private-kernelspec','real-local-kernel-process','Jupyter-channel-readiness','private-interpreter-identity','execute-result-5','actual-error-message','channels-close','kernel-shutdown']

PROBES.update({'pyarrow':arrow_probe,'matplotlib':matplotlib_probe,'seaborn':seaborn_probe,'statsmodels':statsmodels_probe,'datasets':datasets_probe,'nevergrad':nevergrad_probe,'tensorboard':tensorboard_probe,'wandb':wandb_probe,'nbconvert':nbconvert_probe,'ipython':ipython_probe,'ipykernel':ipykernel_probe})
