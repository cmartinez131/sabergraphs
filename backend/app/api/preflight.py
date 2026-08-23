# backend/app/api/preflight.py
"""Deterministic preflight for /api/prompt — runs before any LLM call.

Resolves player mentions (agent/entities.py), extracts requested stats and
intent (rookie / first-N-seasons / compare), checks year coverage, and
decides whether the prompt needs a clarification round-trip.

The clarification questions and every fact in a graceful-gap sentence are
produced HERE, from resolved data — the LLM's only possible role is wording,
never diagnosis, which keeps the "LLM never generates data" invariant
intact for failure messages too.
"""
from dataclasses import dataclass, field

from sqlalchemy import func

from ..agent import entities
from ..agent.common import alias_to_canonical, extract_years
from ..agent.is_baseball_prompt import is_baseball_prompt
from ..db import directory
from ..db.models import BattingStats
from ..toolkit.stats import stat_label

# Offered when a comparison names no stat at all. Every entry is a real
# column (there is no WAR in the Savant exports). The pitching list is used
# when every named player exists only in pitching_stats.
DEFAULT_STAT_CHOICES = [
    "batting_avg", "home_run", "on_base_plus_slg", "woba",
    "slg_percent", "b_rbi", "r_total_stolen_base", "k_percent",
]
PITCHING_STAT_CHOICES = [
    "p_era", "p_win", "p_save", "strikeout", "p_formatted_ip",
    "p_quality_start", "p_opp_batting_avg", "fastball_avg_speed",
]
MAX_PLAYER_OPTIONS = 6


@dataclass
class Preflight:
    gate_ok: bool = True
    mentions: list = field(default_factory=list)
    stats: list = field(default_factory=list)
    rookie: bool = False
    first_n: int | None = None
    compare: bool = False
    forecast: bool = False
    years: list = field(default_factory=list)
    min_year: int | None = None
    max_year: int | None = None
    questions: list = field(default_factory=list)   # ClarifyQuestion dicts

    @property
    def ok_players(self):
        return [m for m in self.mentions if m.status == "ok" and m.resolved]

    @property
    def gap_mentions(self):
        return [m for m in self.mentions if m.status in ("no_data", "unknown")]


def _extract_stats(text, alias_map):
    """Canonical stat columns whose alias phrases appear (word-bounded) in
    `text`, ordered by first occurrence. A phrase nested inside a longer
    matched phrase is suppressed — "home runs" must not also match "runs"."""
    padded = f" {entities.normalize(text)} "
    found = []
    for phrase, col in alias_map.items():
        norm = entities.normalize(phrase)
        pos = padded.find(f" {norm} ")
        if pos >= 0:
            found.append((pos + 1, pos + 1 + len(norm), col))
    found.sort(key=lambda t: (-(t[1] - t[0]), t[0]))   # longest phrase first
    kept = []
    for start, end, col in found:
        if any(start >= ks and end <= ke for ks, ke, _ in kept):
            continue
        kept.append((start, end, col))
    seen, out = set(), []
    for start, _, col in sorted(kept):
        if col not in seen:
            out.append(col)
            seen.add(col)
    return out


def _detect_first_n(tokens):
    """'first 3 seasons' / 'first 3 years' -> 3 (token scan, no regex)."""
    for i, tok in enumerate(tokens):
        if tok == "first" and i + 2 < len(tokens) + 1:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            after = tokens[i + 2] if i + 2 < len(tokens) else ""
            if nxt.isdigit() and after in ("seasons", "years"):
                return int(nxt)
    return None


def _player_question(mention):
    """Clarify question for an ambiguous or unconfirmed mention."""

    def sort_key(c):
        return (
            0 if c.player_id is not None else 1,          # chartable first
            -(c.last_year or 0),                          # most recent data
            0 if c.team else 1,                           # then active people
            -(c.played_last or 0),
        )

    options = []
    for c in sorted(mention.candidates, key=sort_key)[:MAX_PLAYER_OPTIONS]:
        if c.player_id is not None:
            value = {"mention": mention.text, "player_id": int(c.player_id),
                     "name": c.name}
        else:
            value = {"mention": mention.text, "statsapi_id": c.statsapi_id,
                     "name": c.name, "debut": c.debut, "team": c.team}
        options.append({"label": c.name, "description": c.describe() or None,
                        "value": value})
    verb = ("Which" if len(options) > 1 else "Did you mean")
    prompt = (f"{verb} player did you mean by “{mention.text}”?"
              if len(options) > 1 else
              f"Did you mean {options[0]['label']}"
              + (f" ({options[0]['description']})" if options[0]["description"] else "")
              + "?")
    return {"kind": "player", "mention": mention.text, "prompt": prompt,
            "multi": False, "options": options}


def _stat_question(mode="batting"):
    """mode: "batting" | "pitching" | "both". "both" (two-way players, or a
    batter compared against a pitcher) sections the chips into labeled
    groups and pre-selects nothing — that ambiguity is the user's call."""
    if mode == "both":
        options = [
            {"label": stat_label(c), "description": None,
             "value": {"stat": c}, "group": "Batting"}
            for c in DEFAULT_STAT_CHOICES
        ] + [
            {"label": stat_label(c), "description": None,
             "value": {"stat": c}, "group": "Pitching"}
            for c in PITCHING_STAT_CHOICES
        ]
        prompt = ("Batting or pitching comparison? Pick the stats "
                  "(one or more from either group).")
    else:
        pitching = mode == "pitching"
        choices = PITCHING_STAT_CHOICES if pitching else DEFAULT_STAT_CHOICES
        recommended = "p_era" if pitching else "home_run"
        options = [
            {"label": stat_label(col), "description": None,
             "value": {"stat": col}, "recommended": col == recommended}
            for col in choices
        ]
        prompt = ("Which pitching stats should I compare? (pick one or more)"
                  if pitching else
                  "Which stats should I compare? (pick one or more)")
    return {
        "kind": "stat", "mention": None, "multi": True,
        "prompt": prompt,
        "options": options,
    }


def _stat_mode(resolved_local, candidate_pool):
    """Which stat surface to offer, from player roles. Resolved mentions
    anchor; the unchosen candidates of an ambiguous mention only vote when
    nothing is resolved. Two-way players take the surface they share with
    the rest of the comparison; with no one to share with, offer both."""
    roles = {c.role for c in (resolved_local or candidate_pool) if c.role}
    if not roles:
        return "batting"
    if roles == {"pitcher"}:
        return "pitching"
    if roles == {"batter"}:
        return "batting"
    if "two_way" in roles:
        others = roles - {"two_way"}
        if others == {"pitcher"}:
            return "pitching"
        if others == {"batter"}:
            return "batting"
        return "both"
    return "both"  # disjoint batter-vs-pitcher pair


def run_preflight(db, text, hints=None):
    """Resolve entities/stats/intent for `text`; fill clarify questions when
    the prompt cannot be answered unambiguously without the user."""
    pf = Preflight()
    catalog = entities.get_catalog(db)
    player_hints = [h.model_dump() for h in hints.players] if hints else []
    stat_hints = list(hints.stats) if hints else []

    pf.mentions = entities.resolve_mentions(text, catalog, hints=player_hints)

    alias_map = alias_to_canonical()
    pf.stats = stat_hints or _extract_stats(text, alias_map)

    tokens = entities._tokenize(text)
    tokset = set(tokens)
    pf.rookie = bool({"rookie", "rookies"} & tokset) or \
        ("debut" in tokset and {"season", "seasons"} & tokset)
    pf.first_n = _detect_first_n(tokens)
    pf.forecast = bool({"project", "predict", "forecast", "projection"} & tokset)
    pf.compare = (
        len(pf.mentions) >= 2
        or bool({"vs", "versus", "v", "compare", "comparison"} & tokset)
    )
    pf.years = extract_years(text)
    pf.min_year = db.query(func.min(BattingStats.year)).scalar()
    pf.max_year = db.query(func.max(BattingStats.year)).scalar()

    # The keyword gate alone rejects analyst shorthand ("volpe vs lombard jr
    # rookie season" has zero stat vocabulary) — a recognized player name or
    # stat is just as strong a baseball signal.
    any_name_signal = any(
        m.status in ("ok", "ambiguous", "no_data") for m in pf.mentions
    )
    pf.gate_ok = is_baseball_prompt(text) or any_name_signal or bool(pf.stats)

    # Profile enrichment (position / current team) for every candidate that
    # could surface in an option or a narration — cached in player_directory,
    # fetched at most once per player per month, never a hard dependency.
    to_enrich = []
    for m in pf.mentions:
        if m.resolved is not None:
            to_enrich.append(m.resolved)
        if m.status == "ambiguous":
            to_enrich.extend(m.candidates[:MAX_PLAYER_OPTIONS])
    if to_enrich:
        directory.enrich_candidates(db, to_enrich)

    # --- clarification questions ---
    hinted = {entities.normalize(h.get("mention") or "") for h in player_hints}
    for m in pf.mentions:
        if entities.normalize(m.text) in hinted:
            continue  # already answered in a previous round-trip
        if m.status == "ambiguous" and m.candidates:
            pf.questions.append(_player_question(m))
        elif m.status == "no_data" and m.resolved and m.resolved.source == "statsapi":
            # We had to guess beyond the local data — confirm before
            # answering with a gap explanation.
            pf.questions.append(_player_question(m))

    # Ask for stats in the SAME round-trip as any player question, counting
    # still-ambiguous mentions, so the user answers everything at once.
    # Offer pitching chips when every identified player is pitching-only.
    wants_stats = pf.rookie or pf.first_n or (pf.compare and len(pf.mentions) >= 1)
    if wants_stats and not pf.stats and not pf.forecast:
        # Role-based: Kershaw's 50-AB-a-year NL batting rows must not make a
        # Kershaw-vs-Cole comparison offer Home Runs. RESOLVED mentions
        # anchor the context — an ambiguous "cole" pool containing one
        # outfielder must not drag a Kershaw comparison back to batting.
        resolved_local = [m.resolved for m in pf.mentions
                          if m.resolved is not None
                          and m.resolved.player_id is not None]
        cand_local = [c for m in pf.mentions if m.status == "ambiguous"
                      for c in m.candidates if c.player_id is not None]
        pf.questions.append(
            _stat_question(mode=_stat_mode(resolved_local, cand_local)))

    return pf


def coverage_note(pf):
    """Deterministic sentence when requested years exceed the data."""
    beyond = [y for y in pf.years if pf.max_year and y > pf.max_year]
    if not beyond:
        return None
    return (
        f"No data for {', '.join(str(y) for y in sorted(set(beyond)))} — "
        f"this dataset currently covers {pf.min_year}–{pf.max_year}."
    )


def gap_sentences(pf):
    """One factual sentence per unresolvable mention (assembled from
    resolver facts only — nothing invented)."""
    out = []
    for m in pf.gap_mentions:
        c = m.resolved
        if m.status == "no_data" and c is not None:
            detail = ""
            if c.debut:
                detail = f" (MLB debut {c.debut}"
                if c.team:
                    detail += f", {c.team}"
                detail += ")"
            elif c.played_first:
                detail = (f" (played {int(c.played_first)}–"
                          f"{int(c.played_last or c.played_first)})")
            out.append(
                f"Unable to chart {c.name}{detail} — no batting data for "
                f"him in this dataset, which covers {pf.min_year}–{pf.max_year}."
            )
        else:
            out.append(
                f"Couldn't find a player matching “{m.text}” in the "
                f"dataset ({pf.min_year}–{pf.max_year}) or the MLB register."
            )
    return out


def clarify_payload(pf):
    """The canonical 'clarify' response."""
    kinds = {q["kind"] for q in pf.questions}
    if kinds == {"stat"}:
        narr = "Which stats should I compare?"
    elif "stat" in kinds:
        narr = "Quick check before I chart this — confirm the player and pick the stats."
    else:
        narr = "Quick check before I chart this — which player did you mean?"
    return {
        "chart_type": "clarify",
        "series": [],
        "narration": narr,
        "clarification": pf.questions,
        "meta": {"title": "Need a little more detail"},
        "ai_source": "preflight",
    }
