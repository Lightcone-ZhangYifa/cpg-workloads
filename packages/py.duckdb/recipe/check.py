#!/usr/bin/env python3
"""Installed DuckDB check for SQL, durable transactions and local Parquet files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(duckdb, work):
    """Check relational answers, rollback, constraints, persistence and Parquet."""
    database = work / "research.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, category VARCHAR, value DOUBLE NOT NULL)")
        rows = [(1, "a", 1.5), (2, "a", 2.5), (3, "b", 10.0)]
        connection.executemany("INSERT INTO events VALUES (?, ?, ?)", rows)
        grouped = connection.execute("SELECT category, count(*), sum(value) FROM events GROUP BY category ORDER BY category").fetchall()
        require(grouped == [("a", 2, 4.0), ("b", 1, 10.0)], "SQL aggregation mismatch")
        connection.execute("BEGIN TRANSACTION"); connection.execute("INSERT INTO events VALUES (4, 'a', 100)")
        require(connection.execute("SELECT count(*) FROM events").fetchone() == (4,), "Transaction write invisible")
        connection.execute("ROLLBACK")
        require(connection.execute("SELECT count(*) FROM events").fetchone() == (3,), "Rollback failed")
        raises(duckdb.ConstraintException, lambda: connection.execute("INSERT INTO events VALUES (1, 'x', 1)"), "Duplicate key accepted")
        raises(duckdb.ConstraintException, lambda: connection.execute("INSERT INTO events VALUES (4, 'x', NULL)"), "NULL constraint bypassed")
        parquet = work / "events.parquet"
        connection.execute("COPY events TO '" + str(parquet).replace("'", "''") + "' (FORMAT PARQUET)")
        require(connection.execute("SELECT * FROM read_parquet(?) ORDER BY id", [str(parquet)]).fetchall() == rows, "Parquet round trip failed")
        raises(duckdb.ParserException, lambda: connection.execute("SELECT FROM WHERE"), "Malformed SQL accepted")
        raises(duckdb.BinderException, lambda: connection.execute("SELECT absent FROM events"), "Unknown column accepted")
    finally:
        connection.close()
    with duckdb.connect(str(database), read_only=True) as reopened:
        require(reopened.execute("SELECT * FROM events ORDER BY id").fetchall() == rows, "Database persistence failed")
    return {"checks": ["parameterized-inserts", "grouped-sql-answer", "transaction-visibility-and-rollback",
                       "primary-key", "not-null", "parquet-roundtrip", "malformed-sql", "unknown-column", "reopened-database"],
            "rows": len(rows), "scope": "embedded local SQL and Parquet; no remote extensions or network data"}

if __name__ == "__main__":
    raise SystemExit(main("duckdb", "duckdb", functional))
