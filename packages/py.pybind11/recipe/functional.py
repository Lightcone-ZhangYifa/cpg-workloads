import importlib.util,pathlib,subprocess,sys,sysconfig,tempfile,pybind11
with tempfile.TemporaryDirectory(prefix='cpg-pybind11-') as tmp:
    root=pathlib.Path(tmp)
    source=root/'ext.cpp'
    source.write_text('#include <pybind11/pybind11.h>\nint cpg_answer() {return 42;}\nPYBIND11_MODULE(cpg_bind11_fixture,m) { m.def("answer", &cpg_answer); }\n')
    ext=root/('cpg_bind11_fixture'+sysconfig.get_config_var('EXT_SUFFIX'))
    args=['c++','-std=c++17','-O0','-shared','-fPIC','-I'+pybind11.get_include(),'-I'+sysconfig.get_paths()['include'],str(source),'-o',str(ext)]
    subprocess.run(args,check=True,capture_output=True,text=True,timeout=45)
    spec=importlib.util.spec_from_file_location('cpg_bind11_fixture',ext)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert mod.answer()==42
print('CPG_FUNCTIONAL_OK:pybind11:compiled-extension-and-import')
