#!/usr/bin/env python3
"""Installed functional check for sqlalchemy; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(sa, work):
    """Use a real local SQLite database and test commit, rollback and constraints."""
    engine = sa.create_engine("sqlite+pysqlite:///" + str(work / "data.sqlite"))
    metadata = sa.MetaData()
    table = sa.Table("runs", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String, nullable=False, unique=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}])
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(table.insert().values(id=3, name="temporary"))
        transaction.rollback()
        rows = connection.execute(sa.select(table.c.id, table.c.name).order_by(table.c.id)).all()
        require([tuple(row) for row in rows] == [(1, "alpha"), (2, "beta")], "Transaction/rollback mismatch")
    def duplicate():
        with engine.begin() as connection:
            connection.execute(table.insert().values(id=4, name="alpha"))
    raises(sa.exc.IntegrityError, duplicate, "Unique constraint was ignored")
    engine.dispose()
    return {"checks": ["sqlite-schema", "committed-insert", "rollback", "query", "unique-constraint"], "external_database_servers": "not_used"}

if __name__ == "__main__":
    raise SystemExit(main('sqlalchemy', 'sqlalchemy', functional))
