#!/usr/bin/env python3
"""Installed functional check for pandas; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(pd, work):
    """Check deterministic table operations and reject missing-column access."""
    frame = pd.DataFrame({"group": ["a", "b", "a"], "value": [2, 5, 7]})
    grouped = frame.groupby("group", sort=True)["value"].sum().to_dict()
    require(grouped == {"a": 9, "b": 5}, "Group aggregation mismatch")
    joined = frame.merge(pd.DataFrame({"group": ["a", "b"], "weight": [3, 4]}), on="group", validate="many_to_one")
    require(joined["weight"].tolist() == [3, 4, 3], "Join mismatch")
    nullable = pd.Series([1, None, 3], dtype="Int64")
    require(nullable.isna().tolist() == [False, True, False] and nullable.sum() == 4, "Nullable integer mismatch")
    path = work / "table.csv"
    frame.to_csv(path, index=False)
    require(pd.read_csv(path).to_dict("list") == frame.to_dict("list"), "CSV round trip mismatch")
    raises(KeyError, lambda: frame["missing"], "Missing column was accepted")
    return {"checks": ["groupby", "validated-join", "nullable-integers", "csv-roundtrip", "missing-column"], "grouped": grouped}

if __name__ == "__main__":
    raise SystemExit(main('pandas', 'pandas', functional))
