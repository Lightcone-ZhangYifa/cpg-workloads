from pathlib import Path
import os,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probes_v02111_03 import main
if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="cpg-private-settings-",dir=Path.cwd()) as private:
        for key in ("MPLCONFIGDIR","IPYTHONDIR","JUPYTER_CONFIG_DIR","JUPYTER_RUNTIME_DIR","HF_HOME","WANDB_DIR","XDG_CACHE_HOME","HOME"):
            value=Path(private)/key.lower();value.mkdir();os.environ[key]=str(value)
        os.environ["HF_DATASETS_OFFLINE"]="1";os.environ["HF_HUB_OFFLINE"]="1"
        raise SystemExit(main('py.ipython','ipython','IPython'))
