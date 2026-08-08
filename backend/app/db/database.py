# backend/app/db/database.py
import os
import re
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base, Session

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # matches docker-compose's postgres provisioning (user/password/baseball_db)
    "postgresql+psycopg2://user:password@db:5432/baseball_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()

def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------- read-only role for NL->SQL -----------------------
# LLM-generated SQL never runs on the read-write engine above. It executes
# through a dedicated Postgres role with SELECT-only grants, a statement
# timeout, and read-only transactions. The role settings are
# enforced three ways: role-level GUCs (set at provisioning), per-connection
# options below, and the SELECT-only grants themselves.

READONLY_ROLE = os.getenv("NL2SQL_RO_USER", "nl2sql_ro")
READONLY_PASSWORD = os.getenv("NL2SQL_RO_PASSWORD", "nl2sql_ro")
READONLY_STATEMENT_TIMEOUT_MS = 5000


def _derive_readonly_url():
    """READONLY_DATABASE_URL wins; otherwise reuse the main URL with the
    read-only role's credentials (same host/port/database)."""
    override = os.getenv("READONLY_DATABASE_URL")
    if override:
        return override
    return make_url(DATABASE_URL).set(
        username=READONLY_ROLE, password=READONLY_PASSWORD
    )


readonly_engine = create_engine(
    _derive_readonly_url(),
    pool_pre_ping=True,
    future=True,
    connect_args={
        "options": (
            "-c default_transaction_read_only=on "
            f"-c statement_timeout={READONLY_STATEMENT_TIMEOUT_MS}"
        )
    },
)
ReadOnlySessionLocal = sessionmaker(
    bind=readonly_engine, autocommit=False, autoflush=False, future=True
)


@contextmanager
def readonly_session():
    """Session on the read-only role. Fails closed: if the role is missing
    or unreachable, callers get a connection error instead of silently
    executing on the read-write engine."""
    db: Session = ReadOnlySessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_readonly_role():
    """Idempotently provision the read-only role using the main (owner)
    connection. Runs at every backend startup so existing docker volumes get
    the role too; fresh volumes are also covered by
    db/init/01-readonly-role.sh via the postgres docker-entrypoint.
    """
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", READONLY_ROLE):
        raise ValueError(f"Invalid read-only role name: {READONLY_ROLE!r}")
    dbname = make_url(DATABASE_URL).database
    password = READONLY_PASSWORD.replace("'", "''")
    statements = [
        (
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
            f"'{READONLY_ROLE}') THEN CREATE ROLE {READONLY_ROLE} LOGIN; "
            "END IF; END $$;"
        ),
        f"ALTER ROLE {READONLY_ROLE} LOGIN PASSWORD '{password}'",
        f'GRANT CONNECT ON DATABASE "{dbname}" TO {READONLY_ROLE}',
        f"GRANT USAGE ON SCHEMA public TO {READONLY_ROLE}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READONLY_ROLE}",
        # tables loaded later (data_pipeline scripts run as the owner) are
        # covered by default privileges
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {READONLY_ROLE}",
        f"ALTER ROLE {READONLY_ROLE} SET statement_timeout = '5s'",
        f"ALTER ROLE {READONLY_ROLE} SET default_transaction_read_only = on",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()
