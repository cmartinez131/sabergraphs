# data_pipeline/ingest/db.py
"""Engine for the ingestion pipeline (runs on the HOST, not in compose).

Note the 127.0.0.1 default: inside the compose network the DB host is `db`,
but loaders run on the host where compose maps the port (audit S2). We pin
IPv4 because `localhost` can resolve to ::1 first, where an unrelated local
Postgres (e.g. Homebrew) may answer instead of the compose container.
"""
import os

from sqlalchemy import create_engine

HOST_DEFAULT_URL = "postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db"


def get_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL") or HOST_DEFAULT_URL
    return create_engine(url, pool_pre_ping=True, future=True)
