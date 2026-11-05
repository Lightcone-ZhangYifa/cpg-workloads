from pathlib import Path
import os,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probes_v02111_04 import main
if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="cpg-private-settings-",dir=Path.cwd()) as private:
        for key in ("MPLCONFIGDIR","IPYTHONDIR","JUPYTER_CONFIG_DIR","JUPYTER_RUNTIME_DIR","XDG_CACHE_HOME","HOME"):
            value=Path(private)/key.lower();value.mkdir();os.environ[key]=str(value)
        os.environ["JUPYTER_CONFIG_PATH"]="";os.environ["PATH"]=str(Path(sys.prefix)/"bin")
        raise SystemExit(main('py.jupyter-server','jupyter-server','jupyter_server'))
