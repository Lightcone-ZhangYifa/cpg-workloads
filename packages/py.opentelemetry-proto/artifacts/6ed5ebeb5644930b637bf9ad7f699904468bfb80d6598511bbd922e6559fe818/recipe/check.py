from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probes_02 import main
if __name__ == "__main__":
    raise SystemExit(main('py.opentelemetry-proto','opentelemetry-proto','opentelemetry.proto.trace.v1.trace_pb2'))
