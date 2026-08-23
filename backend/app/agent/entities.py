# backend/app/agent/entities.py
"""Deterministic player-entity resolution for natural-language prompts.

Runs BEFORE any LLM call. Every name-like span in the prompt is resolved
against (1) batting_stats — players we can chart, (2) the Chadwick register
— people who exist but have no data in the covered window, and (3) the MLB
StatsAPI people search — failure-path only, so prospects and brand-new
call-ups (e.g. a 2026 debut) can still be identified and explained.

Matching is exact-token, never substring: "lombard" matches George Lombard
and NOT Steve Lombardozzi (the ILIKE '%lombard%' hazard this replaces).
Single-token spans additionally need a qualifying neighbor (vs/and, a stat
word, a suffix, a year) so common surname words in prose — "top young
players" — don't trigger spurious lookups.

Outputs one Mention per name span with a status the caller can act on:
    ok        exactly one player with chartable data          -> proceed
    ambiguous several candidates (two Max Muncys)             -> ask the user
    no_data   a real person with nothing in the covered years -> explain gap
    unknown   no idea who this is                             -> explain gap

The module is pure logic over a catalog dict + injectable search function,
so it unit-tests without a database or network (tests/backend/test_entities.py).
"""
import logging
import time
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger("app.entities")

SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv"}

# Tokens that qualify a lone surname as a real mention when adjacent to it.
_SEPARATOR_TOKENS = {"vs", "versus", "v", "and", "compare", "comparison",
                     "between", "against"}

# Words that can never begin a player mention: chart/compare vocabulary,
# clause words, qualifiers. Stat-alias tokens are added at catalog build
# time so the list tracks the real vocabulary.
_BASE_STOP = {
    "vs", "versus", "v", "and", "or", "the", "a", "an", "in", "on", "of",
    "for", "to", "from", "between", "with", "by", "per", "at", "his", "her",
    "their", "them", "he", "she", "over", "under", "above", "below",
    "compare", "comparison", "show", "chart", "plot", "graph", "top",
    "bottom", "best", "worst", "highest", "lowest", "leaders", "leader",
    "rank", "ranking", "list", "against",
    "rookie", "rookies", "debut", "sophomore", "career", "season", "seasons",
    "year", "years", "first", "last", "next", "min", "max", "minimum",
    "maximum", "qualified", "average", "league", "mlb", "player", "players",
    "batter", "batters", "hitter", "hitters", "stats", "stat", "since",
    "through", "during", "games", "game", "team", "who", "what", "which",
    "how", "many", "much", "left", "right", "handed", "lefty", "righty",
    # superlatives/adjectives that sit next to stat words in prose
    "fastest", "slowest", "most", "least", "fewest", "biggest", "smallest",
    "hardest", "longest", "shortest", "oldest", "youngest", "better",
    "worse", "greatest", "all", "time", "ever", "each", "every", "only",
    "single", "combined", "total", "sum",
}


@dataclass
class Candidate:
    name: str
    player_id: int | None = None        # local id (batting and/or pitching)
    statsapi_id: int | None = None      # MLBAM id from StatsAPI/Chadwick
    first_year: int | None = None       # observed batting range (local only)
    last_year: int | None = None
    has_batting: bool = False           # rows in batting_stats
    has_pitching: bool = False          # rows in pitching_stats
    pitch_first: int | None = None      # observed pitching range
    pitch_last: int | None = None
    career_ab: int | None = None        # summed AB across batting seasons
    bat_seasons: int | None = None
    position: str | None = None
    team: str | None = None
    debut: str | None = None            # StatsAPI mlbDebutDate
    played_first: int | None = None     # Chadwick MLB career range
    played_last: int | None = None
    source: str = "local"               # local | chadwick | statsapi

    @property
    def role(self):
        """"pitcher" | "batter" | "two_way" | None (non-local person).

        NL-era pitchers BAT (Kershaw has 297 career AB), so has_batting
        alone misclassifies them. Measured separation in this dataset:
        pitcher-batting averages 50–57 AB/season, real batters 400+; the
        130 AB/season threshold splits them cleanly. A StatsAPI position
        (P / TWP), when enriched, overrides the heuristic.
        """
        if self.position == "TWP":
            return "two_way"
        if self.position == "P":
            return "pitcher" if self.has_pitching or not self.has_batting \
                else "two_way"
        if self.has_pitching and self.has_batting:
            avg_ab = (self.career_ab or 0) / max(1, self.bat_seasons or 1)
            return "two_way" if avg_ab >= 130 else "pitcher"
        if self.has_pitching:
            return "pitcher"
        if self.has_batting:
            return "batter"
        return None

    def describe(self):
        def span(a, b):
            return f"{a}–{b}" if b and b != a else f"{a}"

        bits = []
        if self.position:
            bits.append(self.position)
        elif self.role == "pitcher":
            bits.append("P")
        elif self.role == "two_way":
            bits.append("2-way")
        if self.team:
            bits.append(self.team)
        if self.has_batting and self.has_pitching:
            bits.append(f"batting {span(self.first_year, self.last_year)}")
            bits.append(f"pitching {span(self.pitch_first, self.pitch_last)}")
        elif self.has_pitching:
            bits.append(f"pitching {span(self.pitch_first, self.pitch_last)}")
        elif self.first_year:
            bits.append(f"data {span(self.first_year, self.last_year)}")
        elif self.debut:
            bits.append(f"MLB debut {self.debut}")
        elif self.played_first:
            bits.append(f"played {int(self.played_first)}–{int(self.played_last or self.played_first)}")
        return " · ".join(bits)


@dataclass
class Mention:
    text: str                            # the span as typed, normalized
    status: str = "unknown"              # ok | ambiguous | no_data | unknown
    candidates: list = field(default_factory=list)
    resolved: Candidate | None = None


def normalize(s):
    """Lowercase, accent-fold, strip periods/commas, collapse whitespace."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace(".", " ").replace(",", " ")
    return " ".join(s.split())


def _last_name_token(norm_name):
    toks = [t for t in norm_name.split() if t not in SUFFIX_TOKENS]
    return toks[-1] if toks else ""


def _has_suffix(norm_name, suffix):
    return suffix in norm_name.split()


# ----------------------- catalog -----------------------
_CATALOG_CACHE = {"built": 0.0, "catalog": None}
CATALOG_TTL_SECONDS = 600


def build_catalog(db):
    """Name index over batting_stats (+profiles positions) and Chadwick.

    {"by_full": {norm full name: [Candidate]},
     "by_last": {last-name token: [Candidate]},
     "stat_tokens": tokens of the stat vocabulary,
     "stop": frozenset of tokens that never begin a name}
    """
    from sqlalchemy import text as sa_text
    from .common import STAT_ALIASES

    by_full, by_last, by_id = {}, {}, {}

    def add(cand):
        norm = normalize(cand.name)
        by_full.setdefault(norm, []).append(cand)
        last = _last_name_token(norm)
        if last:
            by_last.setdefault(last, []).append(cand)
        if cand.player_id is not None:
            by_id[int(cand.player_id)] = cand

    try:
        rows = db.execute(sa_text(
            "SELECT b.player_id, b.full_name, MIN(b.year) AS fy, MAX(b.year) AS ly, "
            "       SUM(COALESCE(b.ab, 0)) AS cab, COUNT(*) AS nsea, "
            "       MAX(p.primary_position) AS pos "
            "FROM batting_stats b "
            "LEFT JOIN player_profiles p ON p.player_id = b.player_id "
            "GROUP BY b.player_id, b.full_name"
        )).mappings().all()
    except Exception:
        # player_profiles is optional (see README quick start) — degrade to
        # names without positions.
        db.rollback()
        rows = db.execute(sa_text(
            "SELECT player_id, full_name, MIN(year) AS fy, MAX(year) AS ly, "
            "       SUM(COALESCE(ab, 0)) AS cab, COUNT(*) AS nsea, "
            "       NULL AS pos "
            "FROM batting_stats GROUP BY player_id, full_name"
        )).mappings().all()
    locals_by_id = {}
    for r in rows:
        pid = int(r["player_id"])
        locals_by_id[pid] = Candidate(
            name=r["full_name"], player_id=pid, statsapi_id=pid,
            first_year=int(r["fy"]), last_year=int(r["ly"]),
            career_ab=int(r["cab"] or 0), bat_seasons=int(r["nsea"] or 0),
            has_batting=True, position=r["pos"], source="local")

    # Pitchers: pitching_stats has its own name universe (2,263 pitchers).
    # Two-way / NL-era players exist in BOTH tables — merge onto one entry.
    try:
        rows = db.execute(sa_text(
            "SELECT player_id, full_name, MIN(year) AS fy, MAX(year) AS ly "
            "FROM pitching_stats GROUP BY player_id, full_name"
        )).mappings().all()
        for r in rows:
            pid = int(r["player_id"])
            if pid in locals_by_id:
                c = locals_by_id[pid]
                c.has_pitching = True
                c.pitch_first, c.pitch_last = int(r["fy"]), int(r["ly"])
            else:
                locals_by_id[pid] = Candidate(
                    name=r["full_name"], player_id=pid, statsapi_id=pid,
                    has_pitching=True,
                    pitch_first=int(r["fy"]), pitch_last=int(r["ly"]),
                    source="local")
    except Exception:
        db.rollback()
        logger.info("pitching_stats unavailable; resolving batters only")

    # Enrich from the persistent StatsAPI profile cache (player_directory)
    # when it exists — cached positions/teams survive restarts, so a player
    # looked up once keeps a "P · Yankees" description forever.
    try:
        rows = db.execute(sa_text(
            "SELECT player_id, position, team, mlb_debut FROM player_directory"
        )).mappings().all()
        for r in rows:
            c = locals_by_id.get(int(r["player_id"]))
            if c is not None:
                c.position = c.position or r["position"]
                c.team = c.team or r["team"]
                c.debut = c.debut or r["mlb_debut"]
    except Exception:
        db.rollback()

    local_ids = set(locals_by_id)
    for cand in locals_by_id.values():
        add(cand)

    try:
        rows = db.execute(sa_text(
            "SELECT key_mlbam, name_first, name_last, mlb_played_first, mlb_played_last "
            "FROM raw_chadwick_people"
        )).mappings().all()
        for r in rows:
            if int(r["key_mlbam"]) in local_ids:
                continue  # the local entry already covers this person
            add(Candidate(
                name=f"{r['name_first']} {r['name_last']}",
                statsapi_id=int(r["key_mlbam"]),
                played_first=r["mlb_played_first"], played_last=r["mlb_played_last"],
                source="chadwick"))
    except Exception:
        logger.info("Chadwick register unavailable; resolving from batting_stats only")

    stat_tokens = set()
    for canon, phrases in STAT_ALIASES.items():
        for phrase in list(phrases) + [canon.replace("_", " ")]:
            for tok in normalize(phrase).split():
                stat_tokens.add(tok)

    return {
        "by_full": by_full,
        "by_last": by_last,
        "by_id": by_id,
        "stat_tokens": frozenset(stat_tokens),
        "stop": frozenset(_BASE_STOP | stat_tokens),
    }


def get_catalog(db):
    """TTL-cached catalog (rebuilding scans two tables)."""
    now = time.monotonic()
    if _CATALOG_CACHE["catalog"] is None or now - _CATALOG_CACHE["built"] > CATALOG_TTL_SECONDS:
        _CATALOG_CACHE["catalog"] = build_catalog(db)
        _CATALOG_CACHE["built"] = now
    return _CATALOG_CACHE["catalog"]


def invalidate_catalog():
    _CATALOG_CACHE["catalog"] = None


# ----------------------- StatsAPI (failure path only) -----------------------
_STATSAPI_CACHE = {}
STATSAPI_URL = ("https://statsapi.mlb.com/api/v1/people/search"
                "?names={q}&hydrate=currentTeam")


def statsapi_search(query):
    """People search against the MLB StatsAPI; [] on any failure."""
    q = normalize(query)
    if q in _STATSAPI_CACHE:
        return _STATSAPI_CACHE[q]
    out = []
    try:
        import requests
        resp = requests.get(STATSAPI_URL.format(q=q.replace(" ", "%20")), timeout=4)
        resp.raise_for_status()
        for p in (resp.json().get("people") or []):
            out.append(Candidate(
                name=p.get("fullName") or "",
                statsapi_id=p.get("id"),
                position=(p.get("primaryPosition") or {}).get("abbreviation"),
                team=(p.get("currentTeam") or {}).get("name"),
                debut=p.get("mlbDebutDate"),
                source="statsapi"))
    except Exception as e:
        logger.info("StatsAPI search failed for %r: %s", query, e)
    _STATSAPI_CACHE[q] = out
    return out


# ----------------------- mention extraction -----------------------
def _tokenize(text):
    out, cur = [], []
    for ch in normalize(text):
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out


def _neighbor_qualifies(tokens, start, end, catalog):
    """A lone surname counts as a mention only next to a separator (vs/and),
    a stat word, a suffix token, or a 4-digit year — or when the prompt is
    essentially just the name."""
    prev_tok = tokens[start - 1] if start > 0 else None
    next_tok = tokens[end] if end < len(tokens) else None
    for tok in (prev_tok, next_tok):
        if tok is None:
            continue
        if tok in _SEPARATOR_TOKENS or tok in SUFFIX_TOKENS:
            return True
        if tok in catalog["stat_tokens"]:
            return True
        if tok.isdigit() and len(tok) == 4:
            return True
    # Essentially-bare-name prompts ("volpe") — measured on ALL tokens, so a
    # surname word buried in a longer sentence never qualifies this way.
    return len(tokens) <= 3


def extract_mentions(text, catalog):
    """Name spans in `text`: known names via the catalog (longest match
    first), plus leftover name-like tokens as unknown mentions so the
    StatsAPI fallback can try them. Returns [(mention_text, candidates)]."""
    tokens = _tokenize(text)
    stop = catalog["stop"]
    n = len(tokens)
    mentions, used = [], [False] * n
    i = 0
    while i < n:
        matched = False
        for size in (3, 2, 1):
            if i + size > n:
                continue
            gram = tokens[i:i + size]
            if gram[0] in stop or gram[0].isdigit():
                break
            phrase = " ".join(gram)
            cands = catalog["by_full"].get(phrase)
            if not cands and size == 1 and len(gram[0]) >= 3:
                cands = catalog["by_last"].get(gram[0])
            if not cands:
                continue
            if size == 1 and not _neighbor_qualifies(tokens, i, i + 1, catalog):
                break  # surname word in prose ("top young players") — skip
            span_end = i + size
            suffix = None
            if span_end < n and tokens[span_end] in SUFFIX_TOKENS:
                suffix = tokens[span_end]
                span_end += 1
            mention_text = " ".join(tokens[i:span_end])
            if suffix:
                kept = [c for c in cands if _has_suffix(normalize(c.name), suffix)]
            else:
                kept = list(cands)
            mentions.append((mention_text, kept))
            for k in range(i, span_end):
                used[k] = True
            i = span_end
            matched = True
            break
        if not matched:
            i += 1

    # Leftover name-like tokens form unknown mentions; consecutive leftovers
    # merge ("george lombard jr"). A LONE leftover is kept only next to a
    # compare separator (vs/and) — stat-word adjacency is not enough, or any
    # stray adjective ("fastest average bat speed") would trigger a lookup.
    def _lone_leftover_ok(start, end):
        prev_tok = tokens[start - 1] if start > 0 else None
        next_tok = tokens[end] if end < n else None
        return any(t in _SEPARATOR_TOKENS for t in (prev_tok, next_tok) if t)

    run_start = None
    for idx in range(n + 1):
        tok = tokens[idx] if idx < n else None
        leftover = (
            tok is not None and not used[idx] and not tok.isdigit()
            and (tok in SUFFIX_TOKENS or (tok not in stop and len(tok) >= 3))
        )
        if leftover:
            if run_start is None:
                run_start = idx
            continue
        if run_start is not None:
            run = tokens[run_start:idx]
            real = [t for t in run if t not in SUFFIX_TOKENS]
            if real and (len(real) > 1 or _lone_leftover_ok(run_start, idx)):
                mentions.append((" ".join(run), []))
            run_start = None
    return mentions


# ----------------------- resolution -----------------------
def resolve_mentions(text, catalog, hints=None, search_fn=None):
    """Resolve every mention in `text`. `hints` is a list of
    {mention, player_id?, statsapi_id?, name?, debut?, team?} dicts from a
    clarification round-trip; a hint pins its mention's resolution.
    `search_fn` late-binds to statsapi_search so tests can monkeypatch."""
    if search_fn is None:
        search_fn = statsapi_search
    hint_map = {}
    for h in (hints or []):
        hint_map[normalize(h.get("mention") or "")] = h

    out = []
    for mention_text, cands in extract_mentions(text, catalog):
        m = Mention(text=mention_text)

        hint = hint_map.get(normalize(mention_text))
        if hint:
            if hint.get("player_id"):
                pid = int(hint["player_id"])
                pinned = [c for c in cands if c.player_id == pid]
                m.resolved = (
                    pinned[0] if pinned
                    else catalog.get("by_id", {}).get(pid)   # keeps data flags
                    or Candidate(name=hint.get("name") or mention_text,
                                 player_id=pid, statsapi_id=pid,
                                 has_batting=True, source="local")
                )
                m.status = "ok"
            else:
                m.resolved = Candidate(
                    name=hint.get("name") or mention_text,
                    statsapi_id=hint.get("statsapi_id"),
                    debut=hint.get("debut"), team=hint.get("team"),
                    source="statsapi")
                m.status = "no_data"
            out.append(m)
            continue

        local = [c for c in cands if c.player_id is not None]
        chadwick = [c for c in cands if c.player_id is None]

        if len(local) == 1:
            m.status, m.resolved, m.candidates = "ok", local[0], local
        elif len(local) > 1:
            m.status, m.candidates = "ambiguous", local
        else:
            # Nobody chartable locally. Merge Chadwick people with a live
            # StatsAPI search so prospects/new call-ups surface too.
            pool = list(chadwick)
            seen = {c.statsapi_id for c in pool if c.statsapi_id}
            want_last = _last_name_token(normalize(mention_text))
            want_suffix = next((t for t in _tokenize(mention_text)
                                if t in SUFFIX_TOKENS), None)
            found = search_fn(mention_text)
            if not found and want_last != normalize(mention_text):
                found = search_fn(want_last)  # retry on surname alone
            for c in found:
                norm = normalize(c.name)
                if _last_name_token(norm) != want_last:
                    continue
                if want_suffix and not _has_suffix(norm, want_suffix):
                    continue
                if c.statsapi_id in seen:
                    continue
                pool.append(c)
                seen.add(c.statsapi_id)
            if len(pool) == 1:
                m.status, m.resolved, m.candidates = "no_data", pool[0], pool
            elif pool:
                m.status, m.candidates = "ambiguous", pool
            else:
                m.status = "unknown"
        out.append(m)
    return out
