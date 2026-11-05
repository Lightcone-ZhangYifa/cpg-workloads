from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from profile_probes import main
if __name__ == "__main__":
    raise SystemExit(main('py.referencing','referencing','referencing'))
