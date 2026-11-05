#!/usr/bin/env python3
"""Installed functional check for pyarrow; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pa, work):
    """Round-trip exact typed data through IPC and Parquet and reject invalid data."""
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq
    table = pa.table({"id": pa.array([1, 2, 3], type=pa.int64()), "name": ["alpha", None, "中文"]})
    parquet = work / "table.parquet"
    pq.write_table(table, parquet, compression="zstd")
    restored = pq.read_table(parquet)
    require(table.equals(restored) and table.schema == restored.schema, "Parquet/schema mismatch")
    target = work / "table.arrow"
    with pa.OSFile(str(target), "wb") as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    with pa.memory_map(str(target), "r") as source:
        require(ipc.open_file(source).read_all().equals(table), "IPC round trip mismatch")
    raises((pa.ArrowInvalid, pa.ArrowTypeError), lambda: pa.array(["wrong"], type=pa.int64()), "Invalid typed array was accepted")
    bad = work / "invalid.parquet"
    bad.write_bytes(b"not a parquet file")
    raises(pa.ArrowInvalid, lambda: pq.read_table(bad), "Invalid Parquet was accepted")
    return {"checks": ["typed-array", "zstd-parquet-roundtrip", "ipc-roundtrip", "schema-and-null-preservation", "invalid-array", "invalid-parquet"], "rows": table.num_rows}

if __name__ == "__main__":
    raise SystemExit(main('pyarrow', 'pyarrow', functional))
