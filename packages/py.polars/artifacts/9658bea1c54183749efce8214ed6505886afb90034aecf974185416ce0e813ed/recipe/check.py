#!/usr/bin/env python3
"""Installed functional check for polars; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pl, work):
    """Execute a lazy aggregation with an exact oracle and local file round trip."""
    frame = pl.DataFrame({"group": ["a", "b", "a"], "value": [2, 5, 7]})
    result = frame.lazy().filter(pl.col("value") >= 2).group_by("group").agg(pl.col("value").sum()).sort("group").collect()
    require(result.to_dict(as_series=False) == {"group": ["a", "b"], "value": [9, 5]}, "Lazy aggregation mismatch")
    path = work / "table.parquet"
    frame.write_parquet(path)
    require(pl.scan_parquet(path).collect().equals(frame), "Lazy Parquet round trip mismatch")
    raises(pl.exceptions.ColumnNotFoundError, lambda: frame.select("missing"), "Unknown column was accepted")
    raises(pl.exceptions.InvalidOperationError, lambda: pl.Series(["bad"]).cast(pl.Int64, strict=True), "Invalid strict cast was accepted")
    return {"checks": ["lazy-filter-aggregate-sort", "parquet-scan-roundtrip", "missing-column", "strict-cast"]}

if __name__ == "__main__":
    raise SystemExit(main('polars', 'polars', functional))
