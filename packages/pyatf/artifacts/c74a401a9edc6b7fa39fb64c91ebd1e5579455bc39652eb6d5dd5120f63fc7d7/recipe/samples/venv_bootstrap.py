import pathlib, runpy, sys
site=pathlib.Path(sys.argv.pop(1)).resolve()
if not site.is_dir():raise RuntimeError("missing private site-packages")
sys.path.append(str(site))
script=sys.argv.pop(1)
sys.argv[0]=script
runpy.run_path(script,run_name="__main__")
