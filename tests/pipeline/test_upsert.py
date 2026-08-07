import pytest
from sqlalchemy import BigInteger, Column, Integer, MetaData, Table, Text, create_engine, select

from data_pipeline.ingest.upsert import upsert_rows


@pytest.fixture()
def engine():
    return create_engine("sqlite://")


@pytest.fixture()
def table(engine):
    md = MetaData()
    t = Table(
        "t", md,
        Column("a", BigInteger, primary_key=True),
        Column("b", Integer, primary_key=True),
        Column("v", Text),
    )
    md.create_all(engine)
    return t


def _all(conn, t):
    return sorted(tuple(r) for r in conn.execute(select(t)))


def test_upsert_inserts_new_rows(engine, table):
    with engine.begin() as conn:
        n = upsert_rows(conn, table, [{"a": 1, "b": 1, "v": "x"}, {"a": 1, "b": 2, "v": "y"}], ["a", "b"])
        assert n == 2
        assert _all(conn, table) == [(1, 1, "x"), (1, 2, "y")]


def test_rerun_never_duplicates(engine, table):
    rows = [{"a": 1, "b": 1, "v": "x"}, {"a": 2, "b": 1, "v": "y"}]
    with engine.begin() as conn:
        upsert_rows(conn, table, rows, ["a", "b"])
        upsert_rows(conn, table, rows, ["a", "b"])  # identical rerun
        assert len(_all(conn, table)) == 2


def test_conflict_updates_non_key_columns(engine, table):
    with engine.begin() as conn:
        upsert_rows(conn, table, [{"a": 1, "b": 1, "v": "old"}], ["a", "b"])
        upsert_rows(conn, table, [{"a": 1, "b": 1, "v": "new"}], ["a", "b"])
        assert _all(conn, table) == [(1, 1, "new")]


def test_empty_rows_is_noop(engine, table):
    with engine.begin() as conn:
        assert upsert_rows(conn, table, [], ["a", "b"]) == 0


def test_batching_splits_large_payloads(engine, table, monkeypatch):
    import data_pipeline.ingest.upsert as upsert_mod

    monkeypatch.setattr(upsert_mod, "MAX_PARAMS_PER_STATEMENT", 9)  # 3 cols -> 3 rows/batch
    rows = [{"a": i, "b": 0, "v": str(i)} for i in range(10)]
    with engine.begin() as conn:
        assert upsert_rows(conn, table, rows, ["a", "b"]) == 10
        assert len(_all(conn, table)) == 10


def test_unknown_dialect_rejected(table):
    class FakeConn:
        class dialect:
            name = "mysql"

    with pytest.raises(NotImplementedError):
        upsert_rows(FakeConn(), table, [{"a": 1, "b": 1, "v": "x"}], ["a", "b"])
