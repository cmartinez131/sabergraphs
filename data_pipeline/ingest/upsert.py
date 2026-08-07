# data_pipeline/ingest/upsert.py
"""Dialect-aware bulk upsert (postgres in production, sqlite in unit tests).

Idempotency contract: re-sending the same rows can never duplicate — the
INSERT lands on the natural-key constraint and turns into an UPDATE.
"""

# Stay under both postgres' and sqlite's bind-parameter limits.
MAX_PARAMS_PER_STATEMENT = 30_000


def upsert_rows(conn, table, rows, conflict_cols):
    """Bulk INSERT ... ON CONFLICT (conflict_cols) DO UPDATE. Returns rows sent."""
    if not rows:
        return 0

    dialect = conn.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        raise NotImplementedError(f"upsert not implemented for dialect {dialect!r}")

    n_cols = max(1, len(rows[0]))
    batch_size = max(1, MAX_PARAMS_PER_STATEMENT // n_cols)

    sent = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        stmt = dialect_insert(table).values(batch)
        update_cols = {
            c.name: getattr(stmt.excluded, c.name)
            for c in table.columns
            if c.name not in conflict_cols
        }
        stmt = stmt.on_conflict_do_update(index_elements=list(conflict_cols), set_=update_cols)
        conn.execute(stmt)
        sent += len(batch)
    return sent
