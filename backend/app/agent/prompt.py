# backend/app/agent/prompt.py
"""
Baseball-aware prompt → plan → execute → chart payload pipeline.

- Translates free-text prompts into a concrete plan (tool + args).
- Executes toolkit functions and returns a canonical payload:
  {
    "chart_type": "<bar|line|radar|histogram|facet>",
    "series": [...],
    "narration": "..."
  }

Key behaviors:
- Robust baseball stat aliasing (rates, x-stats, EV/LA, OAA, etc.).
- Rate-first canonicalization (e.g., "K%" → k_percent) to avoid count-versus-rate confusion.
- Guarded override so canonical hints do NOT clobber good stats already normalized from the text.
- Leaderboard-by-year default (top-1) collapse into a single colored bar series.
- Historical single-year comparisons narrated in past tense; forecasts include method/answer lines.
"""

import os
import json
import difflib
import unicodedata
from datetime import datetime
from sqlalchemy import func
from collections import defaultdict, Counter

# Anthropic SDK optional; fallback works if unavailable.
try:
    import anthropic
except Exception:
    anthropic = None  # type: ignore

from ..db.models import BattingStats
from ..toolkit.stats import (
    compare_players_by_season,
    table_columns,
    compare_multi,
    stat_label,
    label_map_for,
    name_for_id,
    STAT_LABELS as TOOLKIT_LABELS,
    latest_year as stats_latest_year,
    is_rate_stat,
    # --- leaderboard tools ---
    leaderboard,
    leaderboard_range,
    leaderboard_by_year,
)
from ..toolkit.projections import (
    predict_player_stat,
    predict_player_stat_series,
)
from ..toolkit.aging import project_stat_aging_knn

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


# -------------------- Human-readable labels --------------------
STAT_LABELS = dict(TOOLKIT_LABELS)
# Prefer batting stat meanings for lowercase 1b/2b/3b in titles (avoid position names)
STAT_LABELS.update({
    "1b": "Singles",
    "2b": "Doubles",
    "3b": "Triples",
})


def _supported_stats(db):
    """
    Columns that the planner may pick. Start with real DB columns, then
    add virtuals that the toolkit can compute (e.g., OPS).
    """
    cols = set(table_columns(db))
    # Virtuals the toolkit can resolve in stats.resolve_stat_column
    cols.update({"on_base_plus_slg"})  # OPS
    return cols


def replace_stat_tokens(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = []
    tok = ""
    for ch in text:
        if ch.isalnum() or ch == "_":
            tok += ch
        else:
            if tok:
                out.append(STAT_LABELS.get(tok, tok))
                tok = ""
            out.append(ch)
    if tok:
        out.append(STAT_LABELS.get(tok, tok))
    return "".join(out)

def attach_label_metadata(obj: dict) -> dict:
    if not isinstance(obj, dict):
        return obj
    meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
    existing = dict(meta.get("label_map") or {})
    meta["label_map"] = {**STAT_LABELS, **existing}

    title = meta.get("title")
    if isinstance(title, str) and title:
        meta["title_human"] = replace_stat_tokens(title)

    obj["meta"] = meta

    if obj.get("chart_type") == "facet":
        facets = obj.get("facets") or []
        new_facets = []
        for f in facets:
            if not isinstance(f, dict):
                new_facets.append(f); continue
            t = f.get("title")
            if isinstance(t, str) and t:
                f = dict(f); f["title_human"] = replace_stat_tokens(t)
            new_facets.append(f)
        obj["facets"] = new_facets

    return obj


# -------------------- Text normalization helpers --------------------
def strip_accents(s: str) -> str:
    if not isinstance(s, str):
        return s
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def clean(s: str) -> str:
    s = strip_accents(s or "")
    return " ".join(s.split()).strip()

def normalize_for_match(s: str) -> str:
    s = clean(s).lower()
    buf = []
    for ch in s:
        buf.append(ch if (ch.isalnum() or ch == "%") else " ")
    return " ".join("".join(buf).split())

def extract_years(text: str):
    t = normalize_for_match(text)
    years = []
    for token in t.split():
        if token.isdigit() and len(token) == 4:
            y = int(token)
            if 1900 <= y <= 2099:
                years.append(y)
    return years


# -------------------- STAT canonicalization --------------------
# Broad alias coverage: synonyms, abbreviations, and vernacular.
ALIAS_MAP = {
    # Core rates/averages
    "woba": ["woba", "weighted on base average", "weighted on-base average"],
    "xwoba": ["xwoba", "expected woba", "expected weighted on base"],
    "on_base_plus_slg": ["ops", "on base plus slugging", "on-base plus slugging"],
    "on_base_percent": ["obp", "on base percentage", "on-base percentage"],
    "slg_percent": ["slg", "slugging", "slugging percentage"],
    "isolated_power": ["iso", "isolated power"],
    "batting_avg": ["batting average", "avg", "ba"],
    "babip": ["babip", "batting average on balls in play"],
    "wobacon": ["wobacon", "woba on contact", "woba on-contact"],
    "xwobacon": ["xwobacon", "expected wobacon", "x woba on contact"],
    "bacon": ["bacon", "ba on contact", "batting average on contact"],
    "xbacon": ["xbacon", "expected ba on contact", "x ba on contact"],
    "xba": ["xba", "expected batting average", "expected ba"],
    "xslg": ["xslg", "expected slugging"],
    "xobp": ["xobp", "expected obp", "expected on base"],
    "xiso": ["xiso", "expected iso", "expected isolated power"],

    # Counting stats (batting)
    "home_run": ["hr", "homers", "home runs", "homer"],
    "hit": ["hits", "h"],
    "single": ["singles", "1b"],
    "double": ["doubles", "2b"],
    "triple": ["triples", "3b"],
    "strikeout": ["k", "so", "strikeouts"],
    "walk": ["bb", "walks", "base on balls"],
    "b_rbi": ["rbi", "rbis", "runs batted in"],
    "b_total_bases": ["tb", "total bases"],
    "b_hit_by_pitch": ["hbp", "hit by pitch"],
    "b_sac_fly": ["sf", "sac fly", "sacrifice fly"],
    "b_sac_bunt": ["sh", "sac bunt", "sacrifice bunt"],
    "b_gnd_into_dp": ["gidp", "grounded into double play"],
    "b_gnd_into_tp": ["gitp", "grounded into triple play"],
    "b_intent_walk": ["ibb", "intentional walk"],
    "b_reached_on_error": ["roe", "reached on error"],
    "b_total_pitches": ["pitches seen", "total pitches"],

    # Plate-discipline rates
    "bb_percent": ["bb%", "walk%", "walk rate", "bb pct", "bb percentage", "walk %"],
    "k_percent": ["k%", "strikeout%", "strikeout rate", "k pct", "k percentage", "strikeout %"],
    "whiff_percent": ["whiff%", "whiff rate"],
    "swing_percent": ["swing%", "swing rate"],
    "z_swing_percent": ["z-swing%", "zone swing%", "z swing rate"],
    "z_swing_miss_percent": ["z-whiff%", "zone whiff%", "z swing miss%"],
    "oz_swing_percent": ["o-swing%", "chase rate", "o swing%", "chase%"],
    "oz_swing_miss_percent": ["o-whiff%", "o swing miss%"],
    "oz_contact_percent": ["o-contact%", "out of zone contact%"],
    "iz_contact_percent": ["z-contact%", "zone contact%"],
    "f_strike_percent": ["first pitch strike%", "first-pitch strike%"],
    "meatball_percent": ["meatball%", "meatball rate"],
    "meatball_swing_percent": ["meatball swing%", "meatball swing rate"],

    # Contact quality / batted-ball
    "hard_hit_percent": ["hard hit%", "hard-hit%", "hard hit rate"],
    "sweet_spot_percent": ["sweet spot%", "sweet-spot%", "sweet spot rate"],
    "barrel_batted_rate": ["barrel%" , "barrel rate"],
    "barrel": ["barrels"],
    "exit_velocity_avg": ["exit velocity", "exit velo", "avg exit velo", "ev"],
    "launch_angle_avg": ["launch angle", "avg launch angle", "la"],
    "groundballs_percent": ["gb%", "groundball%", "ground ball rate"],
    "flyballs_percent": ["fb%", "flyball%", "fly ball rate"],
    "linedrives_percent": ["ld%", "line drive%", "line-drive rate"],
    "popups_percent": ["pu%", "popup%", "pop up rate"],
    "pull_percent": ["pull%", "pull rate"],
    "opposite_percent": ["oppo%", "opposite field%", "opposite rate"],
    "straightaway_percent": ["straightaway%", "straightaway rate"],

    # Zone aggregates / counts
    "in_zone": ["in-zone pitches", "zone pitches"],
    "out_zone": ["out of zone pitches", "o-zone pitches"],
    "edge_percent": ["edge%", "edge rate"],
    "edge": ["edge pitches"],

    # Pitches seen by type
    "pitch_count": ["pitches seen"],
    "pitch_count_fastball": ["fastballs seen", "fastball seen"],
    "pitch_count_breaking": ["breaking seen", "breaking balls seen"],
    "pitch_count_offspeed": ["offspeed seen"],

    # Running & steals
    "r_total_stolen_base": ["steal", "steals", "stolen base", "stolen bases", "sb"],
    "r_total_caught_stealing": ["caught stealing", "cs"],
    "r_stolen_base_pct": ["sb%", "stolen base%"],
    "r_total_pickoff": ["pickoffs"],
    "r_run": ["runs", "r"],

    # Speed
    "sprint_speed": ["sprint speed", "sprint ft/s", "speed"],
    "n_bolts": ["bolts"],
    "hp_to_1b": ["home to first", "home-to-first", "htf"],

    # Defense/OAA
    "n_outs_above_average": ["oaa", "outs above average"],

    # Misc swing metrics
    "avg_swing_speed": ["swing speed"],
    "avg_swing_length": ["swing length"],
    "fast_swing_rate": ["fast swing%", "fast swing rate"],
    "squared_up_contact": ["squared-up contact", "squared up contact%"],
    "squared_up_swing": ["squared-up swing", "squared up swing%"],
}

def normalize_stat(db, user_stat: str) -> str | None:
    if not user_stat:
        return None
    cols = _supported_stats(db)
    txt = normalize_for_match(user_stat)

    if txt in cols:
        return txt

    for canon, phrases in ALIAS_MAP.items():
        if canon not in cols:
            continue
        for phrase in phrases:
            p = normalize_for_match(phrase)
            hay = f" {txt} "
            needle = f" {p} "
            if needle in hay:
                return canon

    snake = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in user_stat.lower())
    while "__" in snake:
        snake = snake.replace("__", "_")
    snake = snake.strip("_")
    if snake in cols:
        return snake

    shortlist = {
        "home_run","woba","batting_avg","on_base_plus_slg","on_base_percent","slg_percent",
        "isolated_power","barrel_batted_rate","sprint_speed","plate_appearances","pa",
        "player_age","k_percent","bb_percent","r_total_stolen_base","hard_hit_percent",
        "meatball_percent","meatball_swing_percent","b_rbi","exit_velocity_avg","launch_angle_avg",
        "xba","xslg","xwoba","xobp","xiso","wobacon","xwobacon","babip","r_stolen_base_pct",
        "n_outs_above_average",
    } & cols
    candidates = list(shortlist) if shortlist else list(cols)
    match = difflib.get_close_matches(snake, candidates, n=1, cutoff=0.75)
    return match[0] if match else None

def normalize_stats_list(db, stats):
    out = []
    for s in stats or []:
        norm = normalize_stat(db, s)
        if norm:
            out.append(norm)
    return list(dict.fromkeys(out))


# ---------- Canonical stat override from raw text ----------
def canonical_stat_from_text(db, text):
    """
    Return a canonical stat slug inferred directly from raw text.
    IMPORTANT: rate-first detection so "K%" doesn't get mapped to 'strikeout'.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    cols = table_columns(db)
    t = normalize_for_match(text)
    pad = f" {t} "

    def exists(col): return col in cols

    # --- RATE-FIRST: K% / BB% / rates before counts ---
    if (" k% " in pad or " strikeout% " in pad or " strikeout % " in t or " strikeout rate " in t or " k pct " in pad or " k percentage " in t):
        return "k_percent" if exists("k_percent") else None
    if (" bb% " in pad or " walk% " in pad or " walk % " in t or " walk rate " in t or " bb pct " in pad or " bb percentage " in t):
        return "bb_percent" if exists("bb_percent") else None

    if (" ops " in pad) or (" on base plus slugging " in t) or (" on-base plus slugging " in t):
        return "on_base_plus_slg" if exists("on_base_plus_slg") else None
    if " woba " in pad and exists("woba"):
        return "woba"
    if (" obp " in pad) or (" on base percentage " in t) or (" on-base percentage " in t):
        return "on_base_percent" if exists("on_base_percent") else None
    if (" slg " in pad) or (" slugging " in t):
        return "slg_percent" if exists("slg_percent") else None
    if (" iso " in pad) or (" isolated power " in t):
        return "isolated_power" if exists("isolated_power") else None
    if (" batting average " in pad) or (" avg " in pad) or (" ba " in pad):
        return "batting_avg" if exists("batting_avg") else None
    if (" hr " in pad) or (" home run" in t) or (" homers " in pad) or (" homers" in t):
        return "home_run" if exists("home_run") else None

    if " xba " in pad or " expected batting average " in t:
        return "xba" if exists("xba") else None
    if " xslg " in pad or " expected slugging " in t:
        return "xslg" if exists("xslg") else None
    if " xwoba " in pad or " expected woba " in t:
        return "xwoba" if exists("xwoba") else None
    if " xobp " in pad or " expected obp " in t:
        return "xobp" if exists("xobp") else None
    if " xiso " in pad or " expected iso " in t:
        return "xiso" if exists("xiso") else None
    if " babip " in pad:
        return "babip" if exists("babip") else None
    if " rbi " in pad or " runs batted in " in t:
        return "b_rbi" if exists("b_rbi") else None
    if " tb " in pad or " total bases " in t:
        return "b_total_bases" if exists("b_total_bases") else None
    if " steals " in t or " stolen base " in t or " sb " in pad:
        return "r_total_stolen_base" if exists("r_total_stolen_base") else None
    if " whiff " in t:
        return "whiff_percent" if exists("whiff_percent") else None
    if " chase " in t:
        return "oz_swing_percent" if exists("oz_swing_percent") else None
    if " hard hit " in t or " hard-hit " in t:
        return "hard_hit_percent" if exists("hard_hit_percent") else None
    if " barrel " in t:
        return "barrel_batted_rate" if exists("barrel_batted_rate") else ("barrel" if exists("barrel") else None)
    if " exit velocity " in t or " exit velo " in t or " ev " in pad:
        return "exit_velocity_avg" if exists("exit_velocity_avg") else None
    if " launch angle " in t or " la " in pad:
        return "launch_angle_avg" if exists("launch_angle_avg") else None
    if " oaa " in pad or " outs above average " in t:
        return "n_outs_above_average" if exists("n_outs_above_average") else None
    if " sprint speed " in t:
        return "sprint_speed" if exists("sprint_speed") else None

    # --- COUNTS LAST (so they don't steal rate queries) ---
    if " strikeouts " in t or " so " in pad or " k " in pad:
        return "strikeout" if exists("strikeout") else None
    if " walks " in t or " bb " in pad:
        return "walk" if exists("walk") else None

    return None


# -------------------- LLM planning --------------------
def get_llm_client():
    if not ANTHROPIC_API_KEY or anthropic is None:
        return None
    try:
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        return None

def build_system_instructions(allowed_stats):
    allow_str = ", ".join(sorted(allowed_stats))
    return f"""
        Translate baseball analytics prompts into ONE JSON plan the backend can run.
        TOOLS:
        - compare: args {{players:[string|int,...], stat:str, year:int? OR start_year:int & end_year:int}}
        - compare_multi: args {{players:[string|int,...], stats:[str,...], year:int?, start_year:int?, end_year:int?, mode:str?, layout:str?}}
        - leaderboard: args {{stat:str, year:int?, limit:int?, order:'asc'|'desc'?}}
        - leaderboard_range: args {{stat:str, start_year:int, end_year:int, limit:int?, agg:'sum'|'avg'?, order:'asc'|'desc'?}}
        - leaderboard_by_year: args {{stat:str, start_year:int, end_year:int, limit:int?, order:'asc'|'desc'?, min_pa:int?}}
        - predict: args {{player:string|int, stat:str, years:int, horizon:int?, method:str?}}
        RESPONSE: JSON only, no prose. Example:
        {{"tool":"compare","args":{{"players":["David Ortiz","Torii Hunter"],"stat":"home_run","year":2015}}}}
        RULES:
        - The 'stat' or items in 'stats' MUST be among: [{allow_str}].
        - Map natural phrases to these names: batting average→batting_avg, OPS→on_base_plus_slg,
        OBP→on_base_percent, SLG→slg_percent, ISO→isolated_power, HR→home_run, steals/SB→r_total_stolen_base,
        RBI→b_rbi, TB→b_total_bases, HBP→b_hit_by_pitch, IBB→b_intent_walk, xBA→xba, xSLG→xslg, xwOBA→xwoba.
        - 'top/bottom N STAT in YEAR' -> leaderboard with limit=N (order desc/asc).
        - 'top/bottom N STAT between Y1 and Y2' -> leaderboard_range with agg='sum' (or 'avg' if user says average/mean).
        - 'top/bottom N STAT each year between Y1 and Y2' or 'single-season leaders Y1–Y2' -> leaderboard_by_year.
        - 'compare in YEAR' -> compare+year (bar). Year range -> compare+start_year/end_year (line).
        - 'compare X, Y, Z across HR and wOBA in YEAR' -> compare_multi with stats=[...].
        - 'project/predict/forecast' -> predict. Prefer method='aging_knn' for multi-year forecasts.

        QUALIFICATION:
        - For rate stats (any *_percent plus AVG/OBP/SLG/OPS/wOBA/BABIP and x-versions), do NOT add a custom min_pa unless the user explicitly asks.
            The backend automatically enforces MLB Rule 9.22 (3.1 PA per scheduled game) for single years and across spans.
        
        AMBIGUITY / RANGES:
        - If the user gives a range like "2019–2021", infer intent:
            * If they say 'each year', 'by year', etc. → leaderboard_by_year (per-season leaders).
            * If they say 'average' on a rate stat → leaderboard_range with agg='avg'.
            * Else → leaderboard_range with agg='sum' (counts) or 'avg' (rate stats).
        """.strip()


def fewshot_messages(allowed_stats, user_text: str):
    return [
        {"role": "system", "content": build_system_instructions(allowed_stats)},
        {"role": "user", "content": "Compare David Ortiz vs Torii Hunter HR in 2015"},
        {"role": "assistant", "content": json.dumps({
            "tool": "compare",
            "args": {"players": ["David Ortiz", "Torii Hunter"], "stat": "home_run", "year": 2015}
        })},
        {"role": "user", "content": "top 5 players in HR in 2025"},
        {"role": "assistant", "content": json.dumps({
            "tool": "leaderboard",
            "args": {"stat": "home_run", "year": 2025, "limit": 5, "order": "desc"}
        })},
        {"role": "user", "content": "show the top 12 stolen bases total between 2018 and 2020"},
        {"role": "assistant", "content": json.dumps({
            "tool": "leaderboard_range",
            "args": {"stat": "r_total_stolen_base", "start_year": 2018, "end_year": 2020, "limit": 12, "agg": "sum", "order": "desc"}
        })},
        {"role": "user", "content": "single-season HR leaders 2018–2020 (top 3)"},
        {"role": "assistant", "content": json.dumps({
            "tool": "leaderboard_by_year",
            "args": {"stat": "home_run", "start_year": 2018, "end_year": 2020, "limit": 3, "order": "desc"}
        })},
        {"role": "user", "content": "Home run leaders 2020 to 2025"},
        {"role": "assistant", "content": json.dumps({
            "tool": "leaderboard_by_year",
            "args": {"stat": "home_run", "start_year": 2020, "end_year": 2025, "limit": 1, "order": "desc"}
        })},
        {"role": "user", "content": "Project José Ramírez OPS for the next 3 years"},
        {"role": "assistant", "content": json.dumps({
            "tool": "predict",
            "args": {"player": "José Ramírez", "stat": "on_base_plus_slg", "years": 3, "horizon": 3, "method": "aging_knn"}
        })},
        {"role": "user", "content": "Compare José Ramírez and Rafael Devers OPS in 2024"},
        {"role": "assistant", "content": json.dumps({
            "tool": "compare",
            "args": {"players": ["José Ramírez", "Rafael Devers"], "stat": "on_base_plus_slg", "year": 2024}
        })},
        # Teach multi-stat parsing for 1b/2b/3b/hr specifically
        {"role": "user", "content": "compare Aaron Judge and Juan Soto 1b, 2b, 3b, hr in 2025"},
        {"role": "assistant", "content": json.dumps({
            "tool": "compare_multi",
            "args": {
                "players": ["Aaron Judge", "Juan Soto"],
                "stats": ["single", "double", "triple", "home_run"],
                "year": 2025,
                "mode": "players_by_stat",
                "layout": "grouped"
            }
        })},
        
        {"role": "user", "content": user_text},
    ]

def llm_plan_from_text(db, text):
    client = get_llm_client()
    cols = _supported_stats(db)
    allow = sorted([c for c in cols if c not in ("full_name",)])

    if not client:
        return cheap_rules_fallback(db, text)

    try:
        all_messages = fewshot_messages(allow, text)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=all_messages[0]["content"],
            messages=all_messages[1:],
            temperature=0.0,
        )
        raw = (resp.content[0].text or "").strip()
        plan = json.loads(raw)
        if not isinstance(plan, dict) or "tool" not in plan:
            raise ValueError("Bad JSON plan")
        return plan, "llm"
    except Exception:
        return cheap_rules_fallback(db, text)


# -------------------- Name/ID resolution --------------------
def all_player_names(db):
    rows = db.query(BattingStats.full_name).filter(BattingStats.full_name != None).distinct().all()
    return [clean(r[0]) for r in rows if r and r[0]]

def fuzzy_name_lookup(db, name: str) -> str | None:
    names = all_player_names(db)
    if not names:
        return None
    target = clean(name).lower()
    for n in names:
        if target in n.lower():
            return n
    match = difflib.get_close_matches(target, [n.lower() for n in names], n=1, cutoff=0.82)
    if match:
        m = match[0]
        for n in names:
            if n.lower() == m:
                return n
    return None

def resolve_player_ids(db, players_or_ids):
    resolved, seen = [], set()
    for item in players_or_ids or []:
        if isinstance(item, int):
            if item not in seen:
                resolved.append(item); seen.add(item)
            continue
        if not isinstance(item, str) or not item.strip():
            continue
        name = item.strip()
        row = (db.query(BattingStats.player_id)
                 .filter(func.lower(BattingStats.full_name) == name.lower())
                 .order_by(BattingStats.year.desc())
                 .first())
        if not row:
            like = f"%{name.lower()}%"
            row = (db.query(BattingStats.player_id)
                     .filter(func.lower(BattingStats.full_name).like(like))
                     .order_by(BattingStats.year.desc())
                     .first())
        if not row:
            guess = fuzzy_name_lookup(db, name)
            if guess:
                row = (db.query(BattingStats.player_id)
                         .filter(func.lower(BattingStats.full_name) == guess.lower())
                         .order_by(BattingStats.year.desc())
                         .first())
        if row:
            pid = int(row[0])
            if pid not in seen:
                resolved.append(pid); seen.add(pid)
    return resolved

def resolve_single_player_id(db, player_or_id):
    if isinstance(player_or_id, int):
        return player_or_id
    if not isinstance(player_or_id, str) or not player_or_id.strip():
        return None
    name = player_or_id.strip()
    row = (db.query(BattingStats.player_id)
             .filter(func.lower(BattingStats.full_name) == name.lower())
             .order_by(BattingStats.year.desc())
             .first())
    if row:
        return int(row[0])
    like = f"%{name.lower()}%"
    row = (db.query(BattingStats.player_id)
             .filter(func.lower(BattingStats.full_name).like(like))
             .order_by(BattingStats.year.desc())
             .first())
    if row:
        return int(row[0])
    guess = fuzzy_name_lookup(db, name)
    if guess:
        row = (db.query(BattingStats.player_id)
                 .filter(func.lower(BattingStats.full_name) == guess.lower())
                 .order_by(BattingStats.year.desc())
                 .first())
        return int(row[0]) if row else None
    return None

# --------- Single-player detector ---------
def _alias_token_vocab():
    """Lowercased tokens from ALIAS_MAP keys/phrases to filter out stat words."""
    vocab = set()
    for canon, phrases in ALIAS_MAP.items():
        for w in normalize_for_match(canon).split():
            if w:
                vocab.add(w)
        for p in phrases:
            for w in normalize_for_match(p).split():
                if w:
                    vocab.add(w)
    # common glue words / nouns not useful for person detection
    vocab.update({
        "top","best","most","fewest","lowest","bottom","worst","leaders","leaderboard",
        "compare","compared","versus","vs","and","or","with","without","between","to","from","in","of",
        "each","year","years","season","seasons","single","singleseason","by",
        "total","overall","combined","sum","aggregate",
        "avg","average","mean","per","percent","percentage","rate",
        "home","run","runs","rbi","steals","stolen","base","bases","slugging","ops","obp","slg","woba","iso",
    })
    return vocab

def detect_single_player_id_from_text(db, text: str):
    """
    Try to uniquely resolve ONE player from the raw text by probing tokens.
    No regex: uses normalize_for_match + simple splits.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    stop = _alias_token_vocab()
    tokens = [w for w in normalize_for_match(text).split()
              if w and w.isalpha() and len(w) >= 3 and w not in stop]

    found = []
    seen = set()
    for t in tokens:
        pid = resolve_single_player_id(db, t)
        if pid is not None and pid not in seen:
            found.append(pid)
            seen.add(pid)

    return found[0] if len(found) == 1 else None


# -------------------- Intent / horizon --------------------
def parse_horizon(text: str):
    if not isinstance(text, str):
        return None
    t = " ".join((text or "").lower().split())

    if "next season" in t or "coming season" in t:
        return 1

    def number_after_phrase(phrase: str):
        i = t.find(phrase)
        if i == -1:
            return None
        s = t[i + len(phrase):].lstrip()
        j = 0
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == 0:
            return None
        num = s[:j]
        tail = s[j:j+6]
        if "year" not in tail:
            return None
        try:
            n = int(num)
            return n if n >= 1 else None
        except Exception:
            return None

    for p in ["for the next ", "over the next ", "next ", "in "]:
        n = number_after_phrase(p)
        if n is not None:
            return n
    return None

def wants_projection(text: str) -> bool:
    """Determine if the user is asking for a projection/forecast."""
    t = " ".join((text or "").lower().split())

    if any(kw in t for kw in (
        "project", "predict", "forecast",
        "next season", "next year",
        "over the next", "for the next"
    )):
        return True

    # Gentle trigger: "in <N> year(s)" only (avoid matching "in 2024")
    words = t.split()
    for i in range(len(words) - 2):
        if words[i] == "in" and words[i + 1].isdigit() and words[i + 2] in ("year", "years"):
            return True

    return False

def default_current_season() -> int:
    return datetime.now().year


# -------------------- Leaderboard intent detection --------------------
def detect_leaderboard_intent(text: str):
    if not isinstance(text, str):
        return None
    t = normalize_for_match(text)
    words = t.split()

    def is_year_tok(tok: str) -> bool:
        return tok.isdigit() and len(tok) == 4 and 1900 <= int(tok) <= 2099

    asc = any(w in t for w in ["fewest", "lowest", "bottom", "worst"])
    order = "asc" if asc else "desc"

    limit = None
    trigger = {"top", "best", "most", "fewest", "lowest", "bottom", "worst", "leaders", "leaderboard"}
    for i, w in enumerate(words):
        if w in trigger:
            if i + 1 < len(words) and words[i + 1].isdigit() and not is_year_tok(words[i + 1]):
                limit = int(words[i + 1])
            break
    if limit is None and any(w in t for w in trigger):
        limit = 10

    if limit is None:
        return None

    years = extract_years(text)
    agg = "avg" if any(w in t for w in ["avg", "average", "mean", "per year"]) else "sum"
    if "total" in t:
        agg = "sum"

    per_year_triggers = [
        "single season", "single-season", "each year", "by year",
        "year by year", "season by season", "annual", "yearly"
    ]
    explicit_totals = any(w in t for w in ["total", "overall", "combined", "sum", "aggregate"])
    inferred_per_year = (
        any(p in t for p in per_year_triggers) or
        ("leaders" in t and len(years) >= 2 and not explicit_totals and not any(w in t for w in ["avg", "average", "mean"]))
    )
    mode = "per_year" if inferred_per_year else "range"

    # If per-year and the user didn't specify N, show the leader (top-1) each year by default
    if mode == "per_year" and (not isinstance(limit, int) or limit < 1):
        limit = 1

    out = {"limit": limit, "order": order, "agg": agg, "mode": mode}
    if len(years) >= 2:
        out["start_year"], out["end_year"] = years[0], years[1]
    elif len(years) == 1:
        out["year"] = years[0]
    else:
        out["year"] = default_current_season()
    return out


# -------------------- Cheap fallback when LLM is unavailable --------------------
def fallback_stat_from_text(db, t: str) -> str:
    s = normalize_stat(db, t)
    if s:
        return s
    tt = normalize_for_match(t)
    cols = _supported_stats(db)

    # RATE-FIRST guesses
    if ((" k% " in f" {tt} ") or (" strikeout% " in f" {tt} ") or (" strikeout rate " in tt) or (" strikeout % " in tt)) and "k_percent" in cols:
        return "k_percent"
    if ((" bb% " in f" {tt} ") or (" walk% " in f" {tt} ") or (" walk rate " in tt) or (" walk % " in tt)) and "bb_percent" in cols:
        return "bb_percent"

    if "ops" in tt:
        return "on_base_plus_slg" if "on_base_plus_slg" in cols else "home_run"
    if "woba" in tt and "woba" in cols:
        return "woba"
    if "xwoba" in tt and "xwoba" in cols:
        return "xwoba"
    if "xba" in tt and "xba" in cols:
        return "xba"
    if "xslg" in tt and "xslg" in cols:
        return "xslg"
    if "obp" in tt:
        return "on_base_percent" if "on_base_percent" in cols else "home_run"
    if "slg" in tt or "slugging" in tt:
        return "slg_percent" if "slg_percent" in cols else "home_run"
    if "home run" in tt or " hr " in f" {tt} " or "homers" in tt:
        return "home_run"
    if "rbi" in tt and "b_rbi" in cols:
        return "b_rbi"
    if "steal" in tt or " sb " in f" {tt} ":
        return "r_total_stolen_base" if "r_total_stolen_base" in cols else "home_run"
    if "average" in tt or " avg " in f" {tt} " or " ba " in f" {tt} ":
        return "batting_avg" if "batting_avg" in cols else "home_run"
    if "hard hit" in tt and "hard_hit_percent" in cols:
        return "hard_hit_percent"
    if "barrel" in tt and "barrel_batted_rate" in cols:
        return "barrel_batted_rate"
    if "exit velo" in tt and "exit_velocity_avg" in cols:
        return "exit_velocity_avg"
    return "home_run"

def cheap_rules_fallback(db, text):
    lb = detect_leaderboard_intent(text)
    if lb:
        stat = canonical_stat_from_text(db, text) or fallback_stat_from_text(db, text)
        if "start_year" in lb and "end_year" in lb:
            if lb.get("mode") == "per_year":
                return {"tool": "leaderboard_by_year", "args": {
                    "stat": stat, "start_year": lb["start_year"], "end_year": lb["end_year"],
                    "limit": lb["limit"], "order": lb["order"]
                }}, "fallback"
            return {"tool": "leaderboard_range", "args": {
                "stat": stat, "start_year": lb["start_year"], "end_year": lb["end_year"],
                "limit": lb["limit"], "agg": lb["agg"], "order": lb["order"]
            }}, "fallback"
        else:
            return {"tool": "leaderboard", "args": {
                "stat": stat, "year": lb["year"], "limit": lb["limit"], "order": lb["order"]
            }}, "fallback"

    t = normalize_for_match(text)
    years = extract_years(text)
    start_year = end_year = None
    year = None
    if len(years) >= 2:
        start_year, end_year = int(years[0]), int(years[1])
    elif len(years) == 1:
        year = int(years[0])
    stat = fallback_stat_from_text(db, t)

    if "compare" in t:
        return {"tool": "compare", "args": {
            "players": ["Torii Hunter", "David Ortiz"], "stat": stat,
            "year": year, "start_year": start_year, "end_year": end_year
        }}, "fallback"

    if wants_projection(text):
        h = parse_horizon(text) or 1
        return {"tool": "predict", "args": {
            "player": "David Ortiz", "stat": stat, "years": 3, "horizon": h, "method": "aging_knn"
        }}, "fallback"

    return {"tool": "compare", "args": {
        "players": ["Torii Hunter", "David Ortiz"], "stat": stat, "year": year or 2015
    }}, "fallback"


# -------------------- Narration utils --------------------
def fmt_number(v):
    try:
        f = float(v)
    except Exception:
        return str(v)
    if abs(f) >= 100:
        return f"{f:.0f}"
    if abs(f) >= 10:
        return f"{f:.1f}"
    if abs(f) >= 1:
        return f"{f:.3f}".rstrip("0").rstrip(".")
    return f"{f:.3f}".rstrip("0").rstrip(".")

def deterministic_narration(result, plan):
    ct = result.get("chart_type")
    series = result.get("series") or []
    meta = result.get("meta") or {}
    args = (plan or {}).get("args") or {}

    warnings = meta.get("warnings") or []
    warn_note = ""
    if warnings:
        parts = []
        for w in warnings[:3]:
            t = w.get("type")
            if t in ("missing_value", "no_row_for_year"):
                parts.append(f"{w.get('player')} {w.get('stat')} {w.get('year')}")
            elif t == "no_data_in_range":
                parts.append(f"{w.get('player')} ({w.get('start_year')}-{w.get('end_year')})")
        if parts:
            warn_note = f" (missing: {', '.join(parts)})"

    if ct == "bar":
        if len(series) == 1:
            s = series[0]
            pairs = [f"{d['x']} {fmt_number(d['y'])}" for d in (s.get("data") or [])]
            label = s.get("id", "value")
            if args.get("year"):
                return f"{label} in {args['year']}: " + "; ".join(pairs) + warn_note
            return f"{label}: " + "; ".join(pairs) + warn_note
        else:
            chunks = []
            for s in series:
                pairs = [f"{d['x']} {fmt_number(d['y'])}" for d in (s.get("data") or [])]
                chunks.append(f"{s.get('id')}: " + ", ".join(pairs))
            return "; ".join(chunks) + warn_note

    if ct == "line":
        chunks = []
        for s in series:
            pts = s.get("data") or []
            if not pts:
                continue
            last = pts[-1]
            chunks.append(f"{s.get('id')}: {last['x']} {fmt_number(last['y'])}")
        return "Latest values: " + "; ".join(chunks) + warn_note

    if ct == "facet":
        facets = result.get("facets") or []
        return f"{len(facets)} faceted lines generated." + warn_note

    return "Summary unavailable." + warn_note

def polish_narration_with_llm(client, result, draft, forecasting=False):
    if client is None:
        return draft
    try:
        guard = (
            "Write in one or two compact sentences. Include explicit numeric values. "
            "If this is NOT a forecast, strictly use past/present tense and DO NOT use words like "
            "'projected', 'expected', or 'forecast'. Only use those words when forecasting.\n"
        )
        if forecasting:
            guard = (
                "Write in one or two compact sentences. Include explicit numeric values. "
                "This IS a forecast, so future-tense is fine.\n"
            )
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=512,
            system="You are a precise data writer.",
            messages=[
                {"role": "user", "content": guard + f"Draft: {draft}\nChart JSON:\n{json.dumps(result)[:6000]}"},
            ],
            temperature=0.1,
        )
        text = (resp.content[0].text or "").strip()
        return text or draft
    except Exception:
        return draft


# --------- Past-tense helper for historical single-year compares ---------
def value_phrase(stat: str, val: float) -> str:
    if stat == "home_run":
        return f"hit {fmt_number(val)} home runs"
    if stat == "b_rbi":
        return f"drove in {fmt_number(val)} runs"
    if stat == "on_base_plus_slg":
        return f"posted an OPS of {fmt_number(val)}"
    if stat == "on_base_percent":
        return f"posted an OBP of {fmt_number(val)}"
    if stat == "slg_percent":
        return f"slugged {fmt_number(val)}"
    if stat == "woba":
        return f"posted a wOBA of {fmt_number(val)}"
    if stat == "isolated_power":
        return f"posted an ISO of {fmt_number(val)}"
    if stat == "batting_avg":
        return f"batted {fmt_number(val)}"
    return f"posted {stat_label(stat)} {fmt_number(val)}"

def historical_single_year_answer(result: dict, plan: dict) -> str:
    args = (plan or {}).get("args") or {}
    year = args.get("year")
    stat = args.get("stat") or ""
    data = []
    try:
        data = (result.get("series") or [])[0].get("data") or []
    except Exception:
        pass
    if not data:
        return deterministic_narration(result, plan)

    clauses = [f"{d['x']} {value_phrase(stat, d['y'])}" for d in data]
    if len(clauses) == 1:
        answer = f"Answer: In {year}, {clauses[0]}."
    elif len(clauses) == 2:
        answer = f"Answer: In {year}, {clauses[0]} while {clauses[1]}."
    else:
        answer = f"Answer: In {year}, " + ", ".join(clauses[:-1]) + f", and {clauses[-1]}."

    leader = max(data, key=lambda d: d["y"])
    trailer = min(data, key=lambda d: d["y"])
    if leader["x"] != trailer["x"]:
        diff = leader["y"] - trailer["y"]
        unit = "HR" if stat == "home_run" else stat_label(stat)
        answer += f" This comparison highlights {leader['x']}'s lead by {fmt_number(diff)} {unit}."
    return answer


# --------- Forecast narration (aging+KNN) ---------
def build_aging_knn_narration(out: dict, who: str, stat: str, meta_extra: dict, horizon: int) -> str:
    series = out.get("series") or []
    main_id = "Projected " + stat
    main = next((s for s in series if str(s.get("id")) == main_id), None) or (series[0] if series else None)
    p10 = next((s for s in series if str(s.get("id")) == "p10"), None)
    p90 = next((s for s in series if str(s.get("id")) == "p90"), None)

    pts = (main or {}).get("data") or []
    if not pts:
        return "Forecast generated."

    last = pts[-1]
    last_year = last["x"]
    last_val = last["y"]

    byear = meta_extra.get("baseline_year")
    bage  = meta_extra.get("baseline_age")
    k_used = meta_extra.get("k_used")
    tm = meta_extra.get("trend_multiplier")

    age_last = (bage + (last_year - byear)) if (bage is not None and byear is not None) else None

    tech = f"Method: league aging curve blended with KNN comparables (k={k_used}), trend ×{fmt_number(tm)}."
    range_note = ""
    if p10 and p90 and p10.get("data") and p90.get("data"):
        lo = p10["data"][-1]["y"]
        hi = p90["data"][-1]["y"]
        range_note = f" Range p10–p90: {fmt_number(lo)}–{fmt_number(hi)}."

    intro = (
        f"The forecast for {who}'s {stat_label(stat)} over the next {horizon} seasons starts from "
        f"{byear} (age {bage}) and applies aging+KNN comparables. {tech}"
    )
    answer_line = (
        f" Answer: In {last_year}"
        + (f" (age {int(age_last)})" if age_last is not None else "")
        + f", projected {stat_label(stat)}: {fmt_number(last_val)}."
    )
    first_val = pts[0]["y"]
    trend = "stable performance trajectory"
    if last_val > first_val * 1.03:
        trend = "modest upward trajectory"
    elif last_val < first_val * 0.97:
        trend = "modest decline"

    conclusion = f" This analysis suggests a {trend} for {who}, with potential variability in outcomes."
    return intro + range_note + answer_line + conclusion


# --------- Combined narration for top-1 leaders across years ---------
def leaders_combined_answer(stat: str, data, leaders_by_year, start_year: int, end_year: int) -> str:
    if not data or not leaders_by_year:
        return ""
    yrs = list(range(int(start_year), int(end_year) + 1))
    pieces = []
    for y in yrs:
        try:
            v = next(d["y"] for d in data if int(d["x"]) == int(y))
        except StopIteration:
            continue
        name = leaders_by_year.get(int(y))
        if name:
            pieces.append(f"{name} {value_phrase(stat, v)} in {y}")
    if not pieces:
        return ""

    # who led the most seasons?
    counts = Counter(leaders_by_year.values())
    total = len(yrs)
    most_name, most_count = None, 0
    ties = []
    for name, cnt in counts.items():
        if cnt > most_count:
            most_name, most_count = name, cnt
            ties = [name]
        elif cnt == most_count:
            ties.append(name)

    def years_for(player):
        ys = [y for y in yrs if leaders_by_year.get(int(y)) == player]
        return ys

    streak_name, streak_len, streak_start, streak_end = None, 0, None, None
    for name in counts.keys():
        ys = sorted(years_for(name))
        if not ys:
            continue
        run, best, s0, e0, rs, re = 1, 1, ys[0], ys[0], ys[0], ys[0]
        for a, b in zip(ys, ys[1:]):
            if b == a + 1:
                run += 1; re = b
            else:
                if run > best:
                    best, s0, e0 = run, rs, re
                run, rs, re = 1, b, b
        if run > best:
            best, s0, e0 = run, rs, re
        if best > streak_len:
            streak_len, streak_name, streak_start, streak_end = best, name, s0, e0

    if len(pieces) == 1:
        base = f"Answer: {pieces[0]}."
    else:
        base = "Answer: " + ", ".join(pieces[:-1]) + f", and {pieces[-1]}."

    if most_name and len(ties) == 1:
        more = f" Overall, {most_name} led {most_count} of {total} seasons."
    elif most_name and len(ties) > 1:
        names = ", ".join(ties[:-1]) + f", and {ties[-1]}"
        more = f" Overall, there was a tie for most seasons led ({most_count} of {total}) between {names}."
    else:
        more = ""

    streak = ""
    if streak_name and streak_len >= 2:
        streak = f" Longest streak: {streak_name} with {streak_len} straight season(s) from {streak_start}–{streak_end}."

    return (base + more + streak).strip()


# -------------------- Public entry point helpers --------------------
def narration_from_plan(db, plan):
    try:
        tool = plan.get("tool")
        args = plan.get("args") or {}
        if tool == "compare":
            players = args.get("players") or args.get("player_ids") or []
            stat  = args.get("stat")
            if args.get("year"):
                return f"Comparison for {stat} in {args.get('year')} for {players}."
            sy, ey = args.get("start_year"), args.get("end_year")
            if sy and ey:
                return f"Multi-year comparison for {stat} from {sy}–{ey} for {players}."
            return f"Comparison for {stat}."
        if tool == "compare_multi":
            players = args.get("players") or args.get("player_ids") or []
            stats = args.get("stats") or []
            if args.get("year"):
                return f"Multi-stat comparison {stats} in {args.get('year')} for {players}."
            sy, ey = args.get("start_year"), args.get("end_year")
            if sy and ey:
                return f"Multi-stat comparison {stats} from {sy}–{ey} for {players}."
            return f"Multi-stat comparison {stats}."
        if tool == "predict":
            who = args.get("player") or args.get("player_id")
            hor = args.get("horizon")
            meth = args.get("method") or "baseline"
            if hor and hor > 1:
                return f"Forecast for {who} — {args.get('stat')} over next {hor} seasons (method: {meth})."
            if hor == 1:
                return f"Projection for {who} — {args.get('stat')} next season (method: {meth})."
            return f"Projection for {who} — {args.get('stat')} (trailing {args.get('years')} yrs)."
        if tool in ("leaderboard", "leaderboard_range", "leaderboard_by_year"):
            return "Leaderboard."
    except Exception:
        pass
    return "AI summary unavailable."


# -------------------- Utility: multi-stat extraction (no regex) --------------------
def extract_stats_list_from_text(db, text: str) -> list[str]:
    """
    Pick out a list of stats from free text (comma/and separated),
    normalize to canonical slugs, and keep only valid columns.
    No regex used.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    # Lowercase, collapse whitespace
    t = " ".join(text.lower().split())
    # Replace ' and ' with commas to unify separators
    t = t.replace(" and ", ",")
    # Split on commas
    raw_parts = [p.strip() for p in t.split(",") if p.strip()]
    # Some inputs may have space-separated lists without commas; keep single words only
    parts = []
    for p in raw_parts:
        if " " in p:
            # keep simple one/two-token fragments that are likely stats (e.g., "home runs")
            # We'll rely on normalize_stat to accept/reject them.
            parts.extend([q.strip() for q in p.split() if q.strip()])
        else:
            parts.append(p)
    # Normalize and deduplicate in-order
    out, seen = [], set()
    for p in parts:
        s = normalize_stat(db, p)
        if s and s not in seen:
            out.append(s); seen.add(s)
    return out


# -------------------- Public entry point --------------------
def run_prompt(db, text, debug=False):
    plan, source = llm_plan_from_text(db, text)
    tool = (plan or {}).get("tool")
    args = (plan or {}).get("args") or {}

    if "stat" in args:
        norm = normalize_stat(db, args.get("stat"))
        if norm:
            args["stat"] = norm
    if "stats" in args and isinstance(args["stats"], list):
        args["stats"] = normalize_stats_list(db, args["stats"])

    # ---------- IMPORTANT: guarded canonical override ----------
    # Only override when: no current stat; or current isn't a real column; or same-family upgrade.
    def same_family(a, b):
        fams = [
            {"k_percent", "strikeout"},
            {"bb_percent", "walk"},
            # Treat OPS as the same family as its components so an "OPS" hint
            # can override an accidental SLG/OBP selection.
            {"on_base_plus_slg", "slg_percent", "on_base_percent"},
        ]
        for f in fams:
            if a in f or b in f:
                return (a in f) and (b in f)
        return False

    hint = canonical_stat_from_text(db, text)
    if hint:
        current = args.get("stat")
        cols = _supported_stats(db)
        if (not current) or (current not in cols) or same_family(current, hint):
            args["stat"] = hint
        elif "stats" in args and not args.get("stats"):
            args["stats"] = [hint]

    if hint and isinstance(args.get("stats"), list) and args["stats"]:
        upgraded = []
        seen = set()
        for s in args["stats"]:
            s2 = hint if same_family(s, hint) else s
            if s2 not in seen:
                upgraded.append(s2); seen.add(s2)
        args["stats"] = upgraded
        plan["args"] = args

    # --- rescue: if the user clearly lists multiple stats, force compare_multi
    auto_stats = extract_stats_list_from_text(db, text)
    if len(auto_stats) >= 2:
        if tool == "compare":
            args = {
                "players": args.get("players") or args.get("player_ids"),
                "stats": auto_stats,
                "year": args.get("year"),
                "start_year": args.get("start_year"),
                "end_year": args.get("end_year"),
                "mode": args.get("mode") or "players_by_stat",
                "layout": args.get("layout") or "grouped",
            }
            plan = {"tool": "compare_multi", "args": args}
            tool = "compare_multi"
        elif tool == "compare_multi" and not (args.get("stats") or []):
            args["stats"] = auto_stats
            plan["args"] = args

    # ---- normalize planner quirks: single-stat 'compare_multi' → 'compare' ----
    if tool == "compare_multi":
        stats_list = [s for s in (args.get("stats") or []) if s]
        if not stats_list and args.get("stat"):
            stats_list = [args["stat"]]
        if len(stats_list) <= 1:
            stat_slug = stats_list[0] if stats_list else (canonical_stat_from_text(db, text) or "home_run")
            stat_slug = normalize_stat(db, stat_slug) or stat_slug
            args = {
                "players": args.get("players") or args.get("player_ids"),
                "stat": stat_slug,
                "year": args.get("year"),
                "start_year": args.get("start_year"),
                "end_year": args.get("end_year"),
            }
            plan = {"tool": "compare", "args": args}
            tool = "compare"

    # --- Rescue: if the text clearly names ONE player and includes a year range, force a line compare
    detected_pid = detect_single_player_id_from_text(db, text)
    yrs_in_text = extract_years(text)
    if detected_pid and len(yrs_in_text) >= 2:
        y0, y1 = int(yrs_in_text[0]), int(yrs_in_text[1])
        if y0 > y1:
            y0, y1 = y1, y0

        if tool not in ("compare", "compare_multi"):
            stat_hint = args.get("stat") or canonical_stat_from_text(db, text) or "home_run"
            plan = {
                "tool": "compare",
                "args": {"player_ids": [detected_pid], "stat": stat_hint, "start_year": y0, "end_year": y1}
            }
            tool = "compare"
            args = plan["args"]
        else:
            args = dict(args)
            if not args.get("players") and not args.get("player_ids"):
                args["player_ids"] = [detected_pid]
            if "start_year" not in args and "end_year" not in args:
                args["start_year"], args["end_year"] = y0, y1
            plan["args"] = args
            tool = plan["tool"]

    if tool == "predict":
        if not isinstance(args.get("horizon"), int) or args["horizon"] < 1:
            h = parse_horizon(text)
            if h:
                args["horizon"] = int(h)
        if wants_projection(text) and not args.get("method"):
            args["method"] = "aging_knn"

    plan["args"] = args

    # ---- harden leaderboard plans with values from the raw text ----
    if tool in ("leaderboard", "leaderboard_range", "leaderboard_by_year"):
        yrs = extract_years(text)
        tnorm = normalize_for_match(text)

        per_year_keywords = [
            "single season","single-season","each year","by year","year by year",
            "season by season","annual","yearly"
        ]
        explicit_totals = any(w in tnorm for w in ["total","overall","combined","sum","aggregate"])
        wants_per_year = (
            any(p in tnorm for p in per_year_keywords) or
            ("leaders" in tnorm and len(yrs) >= 2 and not explicit_totals and not any(w in tnorm for w in ["avg","average","mean"]))
        )

        if len(yrs) >= 2:
            args.setdefault("start_year", yrs[0])
            args.setdefault("end_year", yrs[1])
            if wants_per_year:
                plan["tool"] = "leaderboard_by_year"
                tool = "leaderboard_by_year"
                if not isinstance(args.get("limit"), int):
                    args["limit"] = 1  # default top-1 per year
            else:
                plan["tool"] = "leaderboard_range"
                tool = "leaderboard_range"
            args.pop("year", None)
        elif len(yrs) == 1:
            args.setdefault("year", yrs[0])

        lim = args.get("limit")
        try:
            lim = int(lim) if lim is not None else None
        except Exception:
            lim = None
        if not isinstance(lim, int) or lim > 1000 or lim < 1:
            args["limit"] = 1 if (wants_per_year and len(yrs) >= 2) else 10
        else:
            args["limit"] = lim

        if "agg" not in args and tool == "leaderboard_range":
            # Prefer avg for rate stats; else use rate hints or sum for counts
            stat_slug = args.get("stat") or canonical_stat_from_text(db, text) or "home_run"
            rate_hints = any(w in tnorm for w in ["avg", "average", "mean", "per year"])
            if is_rate_stat(stat_slug):
                args["agg"] = "avg"
            else:
                args["agg"] = "avg" if rate_hints else "sum"

        if "order" not in args:
            args["order"] = "asc" if any(w in tnorm for w in ["fewest", "lowest", "bottom", "worst"]) else "desc"

        plan["args"] = args

    # ---- harden compare / compare_multi with years pulled from raw text ----
    if tool in ("compare", "compare_multi"):
        yrs = extract_years(text)
        tnorm = normalize_for_match(text)
        wants_by_season = any(p in tnorm for p in [
            "by season", "season by season", "season-by-season",
            "year by year", "each season", "each year"
        ])

        if len(yrs) >= 2:
            y0, y1 = int(yrs[0]), int(yrs[1])
            if y0 > y1:
                y0, y1 = y1, y0
            args["start_year"], args["end_year"] = y0, y1
            args.pop("year", None)
        elif len(yrs) == 1:
            args.setdefault("year", int(yrs[0]))
        elif wants_by_season:
            latest = stats_latest_year(db)
            args["start_year"], args["end_year"] = int(latest) - 4, int(latest)
            args.pop("year", None)

        plan["args"] = args

    client = get_llm_client()

    def _finalize(out, forecasting=False, draft=None):
        if draft is None:
            draft = deterministic_narration(out, plan)
        out["narration"] = polish_narration_with_llm(client, out, draft, forecasting=forecasting)
        if debug:
            out["ai_source"] = source
            out["plan"] = plan
        return attach_label_metadata(out)

    # ---------- leaderboard ----------
    if tool == "leaderboard":
        res = leaderboard(
            db,
            args.get("stat") or canonical_stat_from_text(db, text) or "home_run",
            args.get("year") or default_current_season(),
            args.get("limit", 10),
            args.get("min_pa"),
            args.get("order", "desc"),
        )
        out = {"chart_type": res["chart_type"], "series": res["series"], "meta": res.get("meta", {})}
        return _finalize(out)

    # ---------- leaderboard_range ----------
    if tool == "leaderboard_range":
        res = leaderboard_range(
            db,
            args.get("stat") or canonical_stat_from_text(db, text) or "home_run",
            args.get("start_year"),
            args.get("end_year"),
            args.get("limit", 10),
            args.get("agg", "sum"),
            args.get("order", "desc"),
            args.get("min_pa"),
        )
        out = {"chart_type": res["chart_type"], "series": res["series"], "meta": res.get("meta", {})}
        return _finalize(out)

    # ---------- leaderboard_by_year ----------
    if tool == "leaderboard_by_year":
        sy = args.get("start_year")
        ey = args.get("end_year")
        if sy is None or ey is None:
            yrs = extract_years(text)
            if len(yrs) >= 2:
                sy, ey = yrs[0], yrs[1]
            elif len(yrs) == 1:
                res = leaderboard(
                    db,
                    args.get("stat") or canonical_stat_from_text(db, text) or "home_run",
                    yrs[0],
                    args.get("limit") or 10,
                    args.get("min_pa"),
                    args.get("order") or "desc",
                )
                out = {"chart_type": res["chart_type"], "series": res["series"], "meta": res.get("meta", {})}
                return _finalize(out)
            else:
                latest = stats_latest_year(db)
                sy, ey = latest - 4, latest

        lim = args.get("limit", 10)
        try:
            lim = int(lim)
        except Exception:
            lim = 10

        res = leaderboard_by_year(
            db,
            args.get("stat") or canonical_stat_from_text(db, text) or "home_run",
            int(sy),
            int(ey),
            int(lim),
            args.get("order", "desc"),
            args.get("min_pa"),
        )

        # Collapse top-1 per year into a single bar chart colored by player (legend shows names)
        if int(lim) == 1:
            rng = (res.get("meta") or {}).get("range") or {}
            y0, y1 = int(rng.get("start_year", sy)), int(rng.get("end_year", ey))
            years = list(range(y0, y1 + 1))

            stat = args.get("stat") or "home_run"
            leaders_by_year_map = {}
            per_player = defaultdict(list)  # name -> [{x:year, y:value}, ...]

            for year, facet in zip(years, res.get("facets") or []):
                s0 = (facet.get("series") or [{}])[0]
                pts = s0.get("data") or []
                if not pts:
                    continue
                top = pts[0]  # limit==1
                pname = str(top["x"])
                try:
                    yval = float(top["y"])
                except Exception:
                    continue
                leaders_by_year_map[int(year)] = pname
                per_player[pname].append({"x": int(year), "y": yval})

            def first_year(items):
                return min(int(d["x"]) for d in items) if items else 9999
            series = [
                {"id": player, "data": sorted(points, key=lambda d: int(d["x"]))}
                for player, points in sorted(per_player.items(), key=lambda kv: first_year(kv[1]))
            ]

            # Also produce a flat list of (year,value) to feed the combined narration
            flat_data = [{"x": d["x"], "y": d["y"]} for pts in per_player.values() for d in pts]
            flat_data = sorted(flat_data, key=lambda d: int(d["x"]))

            meta = {
                "title": f"Single-season leaders — {stat_label(stat)} ({y0}–{y1})",
                "label_map": label_map_for([stat]),
                "x_years": years,
                "leaders_by_year": leaders_by_year_map,
                "y_label": stat_label(stat),
                "legend_by": "player",
                # Important: we collapse to one bar per year but still emit one key per player.
                # In grouped mode, Nivo positions the bar at that player's slot inside the year band,
                # which makes the visible bar shift left/right each year and look uneven.
                # Stacked centers the bar in the band's middle, fixing the apparent spacing issue.
                "layout": "stacked",
            }
            out = {"chart_type": "bar", "series": series, "meta": meta}

            draft = leaders_combined_answer(stat, flat_data, leaders_by_year_map, y0, y1) or deterministic_narration(out, plan)
            return _finalize(out, draft=draft)

        # Default facet behavior (limit > 1)
        out = {"chart_type": res["chart_type"], "facets": res["facets"], "meta": res.get("meta", {})}
        return _finalize(out)

    # ---------- compare ----------
    if tool == "compare":
        players = args.get("players")
        player_ids = args.get("player_ids")
        if players and not player_ids:
            player_ids = resolve_player_ids(db, players)
        elif player_ids and isinstance(player_ids, list) and player_ids and isinstance(player_ids[0], str):
            player_ids = resolve_player_ids(db, player_ids)
        elif not player_ids and not players:
            player_ids = resolve_player_ids(db, ["Torii Hunter", "David Ortiz"])

        result = compare_players_by_season(
            db,
            player_ids=player_ids or [],
            stat=args.get("stat") or "home_run",
            year=args.get("year"),
            start_year=args.get("start_year"),
            end_year=args.get("end_year"),
        )

        is_single_year = isinstance(args.get("year"), int)
        latest = stats_latest_year(db)
        is_historical = is_single_year and args["year"] <= int(latest)

        if is_historical:
            result["narration"] = historical_single_year_answer(result, plan)
            if debug:
                result["ai_source"] = source
                result["plan"] = plan
            return attach_label_metadata(result)
        return _finalize(result)

    # ---------- compare_multi ----------
    if tool == "compare_multi":
        res = compare_multi(
            db,
            players=args.get("players") or args.get("player_ids") or ["Torii Hunter", "David Ortiz"],
            stats=args.get("stats") or [args.get("stat") or "home_run"],
            year=args.get("year"),
            start_year=args.get("start_year"),
            end_year=args.get("end_year"),
            mode=args.get("mode") or "players_by_stat",
            layout=args.get("layout") or "grouped",
            normalize=args.get("normalize"),
            window=args.get("window"),
        )
        if res.get("chart_type") == "facet":
            out = {"chart_type": "facet", "facets": res["facets"], "meta": res.get("meta", {})}
        else:
            out = {"chart_type": res["chart_type"], "series": res["series"], "meta": res.get("meta", {})}
        return _finalize(out)

    # ---------- predict ----------
    if tool == "predict":
        player = args.get("player")
        player_id = args.get("player_id") or (resolve_single_player_id(db, player) if player else None)
        stat = args.get("stat") or "woba"
        h = int(args.get("horizon") or parse_horizon(text) or 1)
        method = (args.get("method") or ("aging_knn" if wants_projection(text) else "baseline")).lower()

        if method == "aging_knn":
            series, meta_extra = project_stat_aging_knn(
                db=db,
                db_engine=db.bind,
                player_id=player_id,
                stat=stat,
                horizon=h,
                lookback=int(args.get("years") or 5),
                k=25,
                age_cap=42,
                alpha_comps=0.5,
            )
            title = f"{stat_label(stat)} forecast (aging+KNN, {h} yr{'s' if h>1 else ''})"
            x_years = [pt["x"] for pt in (series[0]["data"] if series and series[0].get("data") else [])]

            label_map = label_map_for([stat])
            label_map.update({
                "p10": "10th percentile (lower bound)",
                "p90": "90th percentile (upper bound)",
                "Projected " + stat: "Projected " + stat_label(stat),
            })

            meta = {
                **(meta_extra or {}),
                "label_map": label_map,
                "title": title,
                "x_years": x_years,
                "bands": {"p10": "lower", "p90": "upper"},
            }
            who = name_for_id(db, player_id) if player_id else (player or "player")

            out = {"chart_type": "line", "series": series, "meta": meta}
            out["narration"] = build_aging_knn_narration(out, who, stat, meta_extra or {}, h)

            if debug:
                out["ai_source"] = source
                out["plan"] = plan
            return attach_label_metadata(out)

        if h > 1:
            path = predict_player_stat_series(
                db, player_id, stat, lookback_years=int(args.get("years") or 3), horizon=h
            )
            series = [{"id": "Projected " + stat, "data": [{"x": y, "y": float(v)} for (y, v) in path]}]
            meta = {"label_map": label_map_for([stat]), "title": f"{stat_label(stat)} forecast ({h} yrs)"}
            out = {"chart_type": "line", "series": series, "meta": meta}

            if series and series[0]["data"]:
                last = series[0]["data"][-1]
                answer_line = f" Answer: In {last['x']}, projected {stat_label(stat)}: {fmt_number(last['y'])}."
            else:
                answer_line = ""
            draft = narration_from_plan(db, plan) + answer_line
            return _finalize(out, forecasting=True, draft=draft)

        v = predict_player_stat(db, player_id, stat, int(args.get("years") or 3))
        y = v if v is not None else 0.0
        out = {
            "chart_type": "bar",
            "series": [{"id": "Projected " + stat, "data": [{"x": "Next season", "y": y}]}],
            "meta": {"label_map": label_map_for([stat]), "title": "Projected " + stat_label(stat)},
        }
        draft = narration_from_plan(db, plan)
        return _finalize(out, forecasting=True, draft=draft)

    # ---------- default ----------
    out = {"chart_type": "bar", "series": [], "meta": {"label_map": {}}}
    out["narration"] = "No plan produced."
    if debug:
        out["ai_source"] = source
        out["plan"] = plan
    return attach_label_metadata(out)
