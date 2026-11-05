from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probes_04 import main
if __name__ == "__main__":
    raise SystemExit(main('py.cma','cma','cma'))
