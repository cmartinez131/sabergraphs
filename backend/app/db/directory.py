# backend/app/db/directory.py
"""player_directory — a persistent cache of MLB StatsAPI people profiles.

Answers "should we always fetch profiles from the API?" with the layered
design the rest of the app uses:

    1. LOCAL FIRST  — names, year ranges and roles come from batting_stats /
       pitching_stats; no network on the happy path.
    2. CACHE SECOND — position / current team / handedness / active flag are
       profile facts the local tables don't carry. They are fetched ONCE per
       player (batched, up to 100 ids per request), stored here, and reused
       for 30 days.
    3. API LAST     — only ids missing from (or stale in) the cache trigger
       a request, and a network failure degrades to whatever is cached.

Profile facts are identity metadata (who someone is), never chart data —
every plotted number still comes from Postgres.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import text as sa_text

logger = logging.getLogger("app.directory")

TABLE = "player_directory"
FRESH_DAYS = 30
BATCH_SIZE = 100
PEOPLE_URL = ("https://statsapi.mlb.com/api/v1/people"
              "?personIds={ids}&hydrate=currentTeam")

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    player_id  BIGINT PRIMARY KEY,
    full_name  TEXT,
    position   TEXT,
    team       TEXT,
    bats       TEXT,
    throws     TEXT,
    active     BOOLEAN,
    mlb_debut  TEXT,
    fetched_at TEXT
)
"""


def ensure_player_directory(engine):
    with engine.begin() as conn:
        conn.execute(sa_text(_CREATE_SQL))


def fetch_people(ids):
    """Batched StatsAPI people lookup -> {id: profile dict}. {} on failure."""
    out = {}
    ids = [int(i) for i in ids]
    try:
        import requests
        for i in range(0, len(ids), BATCH_SIZE):
            chunk = ids[i:i + BATCH_SIZE]
            resp = requests.get(
                PEOPLE_URL.format(ids=",".join(str(x) for x in chunk)),
                timeout=6)
            resp.raise_for_status()
            for p in (resp.json().get("people") or []):
                out[int(p["id"])] = {
                    "full_name": p.get("fullName"),
                    "position": (p.get("primaryPosition") or {}).get("abbreviation"),
                    "team": (p.get("currentTeam") or {}).get("name"),
                    "bats": (p.get("batSide") or {}).get("code"),
                    "throws": (p.get("pitchHand") or {}).get("code"),
                    "active": bool(p.get("active")),
                    "mlb_debut": p.get("mlbDebutDate"),
                }
    except Exception as e:
        logger.info("StatsAPI people lookup failed for %d ids: %s", len(ids), e)
    return out


def _load_cached(db, ids):
    from sqlalchemy import bindparam
    stmt = sa_text(
        f"SELECT player_id, full_name, position, team, bats, throws, active, "
        f"mlb_debut, fetched_at FROM {TABLE} WHERE player_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    rows = db.execute(stmt, {"ids": [int(i) for i in ids]}).mappings().all()
    return {int(r["player_id"]): dict(r) for r in rows}


def _upsert(db, profiles):
    now = datetime.utcnow().isoformat()
    stmt = sa_text(f"""
        INSERT INTO {TABLE}
            (player_id, full_name, position, team, bats, throws, active,
             mlb_debut, fetched_at)
        VALUES (:pid, :full_name, :position, :team, :bats, :throws, :active,
                :mlb_debut, :now)
        ON CONFLICT (player_id) DO UPDATE SET
            full_name = excluded.full_name,
            position = excluded.position,
            team = excluded.team,
            bats = excluded.bats,
            throws = excluded.throws,
            active = excluded.active,
            mlb_debut = excluded.mlb_debut,
            fetched_at = excluded.fetched_at
    """)
    for pid, p in profiles.items():
        db.execute(stmt, {"pid": int(pid), "now": now, **p})
    db.commit()


def _is_fresh(row):
    try:
        fetched = datetime.fromisoformat(row.get("fetched_at") or "")
    except ValueError:
        return False
    return datetime.utcnow() - fetched < timedelta(days=FRESH_DAYS)


def enrich_candidates(db, candidates, fetch_fn=None):
    """Fill position/team/bats/active/mlb_debut on local candidates from the
    cache, fetching (and persisting) only missing or stale ids. Never raises
    — profile enrichment is decoration, not a dependency."""
    if fetch_fn is None:
        fetch_fn = fetch_people
    wanted = {int(c.player_id): c for c in candidates
              if c.player_id is not None and (not c.position or not c.team)}
    if not wanted:
        return
    try:
        db.execute(sa_text(_CREATE_SQL))
        cached = _load_cached(db, list(wanted))
        stale = [pid for pid in wanted
                 if pid not in cached or not _is_fresh(cached[pid])]
        if stale:
            fetched = fetch_fn(stale)
            if fetched:
                _upsert(db, fetched)
                cached.update({pid: {**p, "fetched_at": None}
                               for pid, p in fetched.items()})
        for pid, cand in wanted.items():
            row = cached.get(pid)
            if not row:
                continue
            cand.position = cand.position or row.get("position")
            cand.team = cand.team or row.get("team")
            cand.debut = cand.debut or row.get("mlb_debut")
    except Exception:
        logger.info("player_directory enrichment skipped", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
