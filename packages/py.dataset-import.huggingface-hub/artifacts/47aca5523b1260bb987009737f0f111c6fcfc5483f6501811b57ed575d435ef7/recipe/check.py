from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probes_03 import main
if __name__ == "__main__":
    raise SystemExit(main('py.dataset-import.huggingface-hub','huggingface-hub','huggingface_hub'))
