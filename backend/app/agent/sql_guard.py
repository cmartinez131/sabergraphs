# backend/app/agent/sql_guard.py
"""Isolated SQL safety layer for the NL->SQL path (AUDIT B1/B2).

Every statement produced by the LLM planner must pass ``guard_sql()`` before
it is executed. The checks are pure string/token analysis with no database
or SQLAlchemy dependency, so this module is unit-testable in isolation
(tests/backend/test_sql_guard.py).

Defense in depth: guard_sql() is the first gate. The statement is then
executed through a dedicated read-only Postgres role (SELECT-only grants,
statement_timeout, default_transaction_read_only) provisioned in
db/database.py — so even a statement that somehow slipped the guard could
not write to or block the database.

Guard rules, in order:
 1. Backslashes are rejected outright (E'..' escape obfuscation).
 2. Comments are stripped string-aware; a comment becomes a single space,
    matching Postgres tokenization, so ``SEL/**/ECT`` does NOT become
    ``SELECT``.
 3. String literals are masked before any token check, so a player named
    "Grant" cannot false-positive the keyword scan.
 4. Double quotes and dollar signs are rejected outside string literals
    (quoted-identifier and $$-quoting obfuscation; the planner never
    emits either).
 5. Exactly one statement: a semicolon may only appear at the very end.
 6. The leading keyword must be SELECT — an allowlist, not a denylist.
 7. Deny-keywords (DDL/DML/session/admin/set-ops) may not appear anywhere,
    even though rules 5-6 already make them unreachable as statements.
 8. System surfaces are rejected: information_schema and any pg_* token.
 9. Every table referenced in FROM/JOIN — including comma-separated FROM
    lists, aliases, and derived tables — must be in ALLOWED_TABLES.
10. Join alignment: joins must mention player_id (or batter_mlbam, the
    same MLBAM id space used by the pitch-level mart tables); joins
    involving player_features/player_seasons must also align on year, and
    joins involving mart tables must align on season.
11. A hard LIMIT cap (default 200) is enforced on the top-level statement.

Note the raw_/staging_ pipeline layers are deliberately NOT allowlisted:
the NL->SQL surface only sees the curated mart tables.
"""

# Season-grain mart tables produced by the pitch-level pipeline
# (data_pipeline/ingest). Keyed on (batter_mlbam, season).
MART_TABLES = frozenset({
    "mart_batter_pitch_season",
    "mart_bat_tracking_season",
})

ALLOWED_TABLES = frozenset({
    "batting_stats",
    "player_profiles",
    "player_features",
    "player_seasons",
}) | MART_TABLES

DEFAULT_MAX_ROWS = 200

# Exact-token matches only, checked after string masking and dot-splitting,
# so snake_case stat columns (strikeout, single, double, start_year, ...)
# can never collide with an entry here.
DENIED_KEYWORDS = frozenset({
    # DML / DDL
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "merge", "into", "returning", "import", "comment",
    # server-side execution / session control
    "copy", "call", "do", "set", "reset", "discard", "load", "prepare",
    "deallocate", "execute", "declare", "explain",
    # maintenance / locking
    "vacuum", "analyze", "analyse", "cluster", "reindex", "checkpoint",
    "lock", "listen", "unlisten", "notify", "refresh",
    # transaction control (a second statement is already blocked; belt+braces)
    "begin", "commit", "rollback", "savepoint", "abort", "start",
    # cursors / row locks
    "fetch", "move", "close", "share",
    # set operations and exotic FROM items the planner never emits
    "union", "intersect", "except", "lateral",
    # remote / file access helpers
    "dblink", "lo_import", "lo_export",
})

# Words that terminate a table reference (so they are never read as an alias).
_CLAUSE_KEYWORDS = frozenset({
    "where", "group", "order", "limit", "offset", "having", "on", "using",
    "join", "inner", "left", "right", "full", "cross", "natural", "as",
    "and", "or", "not", "select", "from", "window", "for", "fetch",
    "union", "intersect", "except", "returning", "tablesample",
})

_WORD_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_."
)

_PUNCT = ("(", ")", ",", ";")


class SqlGuardError(ValueError):
    """A candidate SQL statement failed a safety check."""


# ----------------------- lexing helpers -----------------------
def strip_sql_comments(sql):
    """Remove -- and /* */ comments, string-aware and nesting-aware.

    Each comment is replaced by a single space (Postgres treats comments as
    token separators, so joining the surrounding text would *create* tokens
    that Postgres itself would never see).
    """
    if not isinstance(sql, str):
        return ""
    out = []
    i, n = 0, len(sql)
    in_string = False
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "'":
                if nxt == "'":          # '' escape stays inside the string
                    out.append(nxt)
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":    # line comment: drop through end of line
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            out.append(" ")
            continue
        if ch == "/" and nxt == "*":    # block comment: Postgres nests these
            depth = 1
            i += 2
            while i < n and depth:
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    depth += 1
                    i += 2
                elif sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def mask_string_literals(sql):
    """Replace the contents of single-quoted literals with spaces.

    Length-preserving (positions still line up with the input), so token
    positions found on the masked text can be used to edit the original.
    Raises on an unterminated literal.
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append("'")
            i += 1
            closed = False
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("  ")
                        i += 2
                        continue
                    out.append("'")
                    i += 1
                    closed = True
                    break
                out.append(" ")
                i += 1
            if not closed:
                raise SqlGuardError("Unterminated string literal.")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _lex(masked):
    """Tokenize masked SQL into (text, position) pairs.

    Words keep embedded dots (``b.full_name`` is one token); of the
    punctuation only ``( ) , ;`` matter to the guard, everything else
    (operators, quotes, whitespace) is skipped.
    """
    tokens = []
    i, n = 0, len(masked)
    while i < n:
        ch = masked[i]
        if ch in _WORD_CHARS:
            j = i
            while j < n and masked[j] in _WORD_CHARS:
                j += 1
            tokens.append((masked[i:j], i))
            i = j
        elif ch in _PUNCT:
            tokens.append((ch, i))
            i += 1
        else:
            i += 1
    return tokens


def tokenize_identifiers(sql):
    """Split into bare identifier/number words (dots split; no punctuation).

    Kept for the narration helpers in nl2sql.py (limit/order parsing).
    """
    tokens, current = [], []
    for ch in sql:
        if ch.isalnum() or ch == "_":
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


# ----------------------- table extraction -----------------------
def _skip_group(tokens, i):
    """tokens[i] is '('; return the index just past its matching ')'."""
    depth = 0
    n = len(tokens)
    while i < n:
        if tokens[i][0] == "(":
            depth += 1
        elif tokens[i][0] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _consume_table_item(tokens, i, tables):
    """Consume one table reference (name or derived table, plus optional
    alias) starting at token index i. Returns the index after it."""
    n = len(tokens)
    if i >= n:
        return i
    text = tokens[i][0]
    if text == "(":
        # derived table: recurse so its inner FROM/JOIN tables are collected
        end = _skip_group(tokens, i)
        tables.extend(_extract_tables(tokens[i + 1:max(i + 1, end - 1)]))
        i = end
    elif text in _PUNCT:
        return i
    else:
        name = text.split(".")[-1].lower()
        if name in _CLAUSE_KEYWORDS or not name:
            return i
        tables.append(name)
        i += 1
    # optional alias: [AS] word
    if i < n and tokens[i][0].lower() == "as":
        i += 1
        if i < n and tokens[i][0] not in _PUNCT:
            i += 1
    elif i < n and tokens[i][0] not in _PUNCT \
            and tokens[i][0].lower() not in _CLAUSE_KEYWORDS:
        i += 1
    return i


def _consume_from_list(tokens, i, tables):
    """Consume a comma-separated FROM list starting at token index i."""
    n = len(tokens)
    while True:
        j = _consume_table_item(tokens, i, tables)
        if j == i:
            return i
        i = j
        if i < n and tokens[i][0] == ",":
            i += 1
            continue
        return i


def _extract_tables(tokens):
    tables = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i][0].lower()
        if t == "from":
            i = max(_consume_from_list(tokens, i + 1, tables), i + 1)
        elif t == "join":
            i = max(_consume_table_item(tokens, i + 1, tables), i + 1)
        else:
            i += 1
    return tables


def tables_in_from_join(sql):
    """Every table referenced in FROM or JOIN, schema prefix removed,
    deduplicated in first-seen order. This is the B1 fix: FROM tables are
    detected (the old substring scan compared a 5-char slice against the
    6-char ``" from "`` and never matched), comma lists and derived tables
    are handled, and the result is validated in full by guard_sql()."""
    masked = mask_string_literals(strip_sql_comments(sql))
    found = _extract_tables(_lex(masked))
    seen, unique = set(), []
    for t in found:
        if t not in seen:
            unique.append(t)
            seen.add(t)
    return unique


# ----------------------- LIMIT enforcement -----------------------
def _enforce_limit(clean, masked, max_rows):
    """Cap the top-level LIMIT at max_rows; append one if absent.

    Only a LIMIT at parenthesis depth 0 counts — a LIMIT inside a subquery
    does not bound the outer statement.
    """
    body_end = len(clean.rstrip())
    if clean[:body_end].endswith(";"):
        body_end -= 1
    clean_body = clean[:body_end]
    masked_body = masked[:body_end]

    tokens = _lex(masked_body)
    depth = 0
    limit_idx = None
    for k, (text, _pos) in enumerate(tokens):
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
        elif depth == 0 and text.lower() == "limit":
            limit_idx = k

    if limit_idx is None:
        return clean_body.rstrip() + f" LIMIT {max_rows};"

    if limit_idx + 1 >= len(tokens):
        raise SqlGuardError("LIMIT requires a literal integer value.")
    value, value_pos = tokens[limit_idx + 1]
    if not value.isdigit():
        raise SqlGuardError("LIMIT requires a literal integer value.")
    if int(value) > max_rows:
        clean_body = (
            clean_body[:value_pos] + str(max_rows)
            + clean_body[value_pos + len(value):]
        )
    return clean_body.rstrip() + ";"


# ----------------------- main entry point -----------------------
def guard_sql(sql, allowed_tables=ALLOWED_TABLES, max_rows=DEFAULT_MAX_ROWS):
    """Validate a candidate statement and return it execution-ready
    (comments stripped, LIMIT capped, single trailing semicolon).

    Raises SqlGuardError on any violation.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardError("Empty SQL statement.")
    if "\\" in sql:
        raise SqlGuardError("Backslashes are not allowed.")

    clean = strip_sql_comments(sql).strip()
    masked = mask_string_literals(clean)

    if '"' in masked:
        raise SqlGuardError("Double-quoted identifiers are not allowed.")
    if "$" in masked:
        raise SqlGuardError("Dollar quoting is not allowed.")

    body = masked.rstrip()
    if body.endswith(";"):
        body = body[:-1]
    if ";" in body:
        raise SqlGuardError("Multiple SQL statements are not allowed.")

    tokens = _lex(masked)
    words = [t.lower() for t, _ in tokens if t not in _PUNCT]
    if not words or words[0] != "select":
        raise SqlGuardError("Only single SELECT statements are allowed.")

    # exact-token deny list, split on dots so a.b qualifies both parts
    pieces = set()
    for w in words:
        for piece in w.split("."):
            if piece:
                pieces.add(piece)
    denied = pieces & DENIED_KEYWORDS
    if denied:
        raise SqlGuardError(f"Disallowed keyword: {sorted(denied)[0]}")
    if "information_schema" in pieces:
        raise SqlGuardError("System schemas are not allowed.")
    for piece in pieces:
        if piece.startswith("pg_"):
            raise SqlGuardError("System catalogs and pg_* functions are not allowed.")

    used_tables = tables_in_from_join(clean)
    if not used_tables:
        raise SqlGuardError("Query must reference at least one table.")
    for table in used_tables:
        if table not in allowed_tables:
            raise SqlGuardError(f"Table not allowed: {table}")

    if "join" in pieces and "player_id" not in pieces \
            and "batter_mlbam" not in pieces:
        raise SqlGuardError("Joins must include player_id/batter_mlbam equality.")
    if {"player_features", "player_seasons"} & set(used_tables) \
            and "year" not in pieces:
        raise SqlGuardError("Joins with features/seasons must align on year.")
    if MART_TABLES & set(used_tables) and len(set(used_tables)) > 1 \
            and "season" not in pieces:
        raise SqlGuardError("Joins with mart tables must align on season.")

    return _enforce_limit(clean, masked, max_rows)
