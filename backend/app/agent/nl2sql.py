"""Schema-aware NL → SQL pipeline. Returns { chart_type, series, narration, meta }."""

import os
import json

from sqlalchemy import text as sa_text
from sqlalchemy import inspect as sa_inspect

from ..toolkit.stats import table_columns, label_map_for
from ..toolkit.stats import (
    stat_label,
    is_rate_stat,
    _pa_column_name,
    _qualified_pa_threshold,
)

try:
    import anthropic  # type: ignore
except Exception:
    anthropic = None  # type: ignore

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

ALLOWED_TABLES = {
    "batting_stats",
    "player_profiles",
    "player_features",
    "player_seasons",
}

# ----------------------- LLM wrapper -----------------------
def get_llm_client():
    if not ANTHROPIC_API_KEY or anthropic is None:
        return None
    try:
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        return None


def reflect_table_columns(db, table_name):
    try:
        inspector = sa_inspect(db.bind)
        columns = inspector.get_columns(table_name)
        return [c["name"] for c in columns]
    except Exception:
        return []


def build_catalog(db):
    catalog = {
        "batting_stats": sorted(table_columns(db)),
        "player_profiles": reflect_table_columns(db, "player_profiles"),
        "player_features": reflect_table_columns(db, "player_features"),
        "player_seasons": reflect_table_columns(db, "player_seasons"),
    }
    # Ensure virtual OPS is available to the planner even if not a physical column
    if "on_base_plus_slg" not in catalog["batting_stats"]:
        catalog["batting_stats"] = sorted(set(catalog["batting_stats"]) | {"on_base_plus_slg"})
    return catalog


# ----------------------- Analyst aliasing -----------------------
ALIAS_BASE = {
    # Core rate/average
    "ops": "on_base_plus_slg",
    "on-base plus slugging": "on_base_plus_slg",
    "slugging %": "slg_percent",
    "slugging percentage": "slg_percent",
    "slg": "slg_percent",
    "obp": "on_base_percent",
    "on-base %": "on_base_percent",
    "on-base percentage": "on_base_percent",
    "avg": "batting_avg",
    "ba": "batting_avg",
    "batting average": "batting_avg",
    "woba": "woba",
    "xwoba": "xwoba",
    "wobacon": "wobacon",
    "xwobacon": "xwobacon",
    "xslg": "xslg",
    "xobp": "xobp",
    "xba": "xba",
    "xiso": "xiso",
    "iso": "isolated_power",
    "babip": "babip",

    # Plate discipline
    "k%": "k_percent",
    "k pct": "k_percent",
    "strikeout %": "k_percent",
    "strike out percentage": "k_percent",
    "strikeout percentage": "k_percent",
    "k rate": "k_percent",
    "bb%": "bb_percent",
    "walk %": "bb_percent",
    "walk rate": "bb_percent",
    "whiff %": "whiff_percent",
    "whiff rate": "whiff_percent",
    "swing %": "swing_percent",
    "z-swing %": "z_swing_percent",
    "z-whiff %": "z_swing_miss_percent",
    "o-swing %": "oz_swing_percent",
    "o-whiff %": "oz_swing_miss_percent",
    "o-contact %": "oz_contact_percent",
    "z-contact %": "iz_contact_percent",
    "first-pitch strike %": "f_strike_percent",
    "meatball %": "meatball_percent",
    "meatball swing %": "meatball_swing_percent",

    # Batted-ball quality
    "hard-hit %": "hard_hit_percent",
    "sweet-spot %": "sweet_spot_percent",
    "barrel %": "barrel_batted_rate",
    "pull %": "pull_percent",
    "opposite %": "opposite_percent",
    "straightaway %": "straightaway_percent",
    "groundball %": "groundballs_percent",
    "flyball %": "flyballs_percent",
    "line-drive %": "linedrives_percent",
    "popup %": "popups_percent",
    "exit velocity": "exit_velocity_avg",
    "avg exit velocity": "exit_velocity_avg",
    "launch angle": "launch_angle_avg",
    "avg launch angle": "launch_angle_avg",

    # Counting stats (batting)
    "hr": "home_run",
    "home runs": "home_run",
    "homers": "home_run",
    "rbi": "b_rbi",
    "rbis": "b_rbi",
    "runs batted in": "b_rbi",
    "hits": "hit",
    "singles": "single",
    "doubles": "double",
    "triples": "triple",
    "walks": "walk",
    "strikeouts": "strikeout",
    "total bases": "b_total_bases",
    "hbp": "b_hit_by_pitch",

    # Baserunning
    "sb": "r_total_stolen_base",
    "steals": "r_total_stolen_base",
    "stolen bases": "r_total_stolen_base",
    "caught stealing": "r_total_caught_stealing",
    "sprint speed": "sprint_speed",

    # Defense / Statcast fielding
    "oaa": "n_outs_above_average",

    # Position / meta
    "position": "primary_position",
}

def _normalize_key(s: str) -> str:
    return " ".join((s or "").lower().replace("%", " % ").split())

def _reverse_human_labels_to_columns(db, cols):
    """Build reverse map from human labels (stat_label) back to canonical column names."""
    rev = {}
    for c in cols:
        human = stat_label(c)
        if not human:
            continue
        k1 = _normalize_key(human)
        rev[k1] = c
        k2 = _normalize_key(human.replace(" %", "%"))
        rev.setdefault(k2, c)
        if human.lower() == "home runs":
            rev.setdefault("hr", c)
        if human.lower() == "rbis":
            rev.setdefault("rbi", c)
    return rev

def build_alias_catalog(db, catalog):
    """Build alias catalog filtered to present DB columns."""
    cols = set(catalog.get("batting_stats") or [])
    aliases = {k: v for k, v in ALIAS_BASE.items() if v in cols}
    aliases.update(_reverse_human_labels_to_columns(db, cols))
    return aliases


# ----------------------- Prompt builder -----------------------
def build_schema_prompt(db, catalog, alias_catalog):
    def joinColumns(table_name):
        columns = ", ".join(sorted(catalog.get(table_name, [])))
        return f"{table_name}({columns})"
    schema_lines = [joinColumns(t) for t in ALLOWED_TABLES]
    schema_block = "\n".join(schema_lines)

    alias_block = json.dumps(alias_catalog, ensure_ascii=False, indent=2)

    return f"""
You are a SQL planner for MLB batting data. You write ONE safe Postgres SELECT using ONLY the allowed tables/columns below.
Always use exact column names from this schema. When the user uses analyst terms, translate them using the alias map.

SCHEMA (allowed tables and columns):
{schema_block}

STAT ALIASES (natural language → column name):
{alias_block}

Join & alignment rules:
- ALWAYS join on player_id when combining tables.
- If joining player_features or player_seasons with batting_stats, also join on year (both player_id AND year).
  Example:
    FROM batting_stats b
    JOIN player_features f ON f.player_id = b.player_id AND f.year = b.year
- player_profiles is per-player; join on player_id only.
- Compute OPS as (on_base_percent + slg_percent) AS on_base_plus_slg when needed.

Constraints:
- Output JSON only (no prose), with exactly these keys: sql, x, y, chart_type, assumptions.
- SELECT-only, single statement (no UNION/CTE/DDL/DML).
- Use only allowed tables/columns listed above.
- Alias projected fields to simple names that match your JSON "x"/"y".
- Single year: WHERE <table>.year = YYYY
- Range: WHERE <table>.year BETWEEN Y1 AND Y2
- Ranking: include ORDER BY and LIMIT (default LIMIT 50 if user doesn't say)
- Chart types: choose "bar" (categorical x) or "line" (time series)
- If the prompt names a SINGLE PLAYER and a YEAR RANGE, return a per-year time series:
  SELECT b.year AS year, <stat> AS value
  FROM batting_stats b
  WHERE b.full_name ILIKE '%<player>%' AND b.year BETWEEN Y1 AND Y2
  ORDER BY year ASC;
  Use chart_type="line". Do NOT aggregate or LIMIT.

Return JSON:
{{
  "sql": "SELECT ...",
  "x": "x_axis_column",
  "y": "y_axis_column_or_list",
  "chart_type": "bar|line",
  "assumptions": "short note if any"
}}
""".strip()


def fewshot_messages(db, catalog, alias_catalog, user_text):
    system_prompt = build_schema_prompt(db, catalog, alias_catalog)
    return [
        {"role": "system", "content": system_prompt},

        # Simple leaderboard — demonstrates alias usage (HR)
        {"role": "user", "content": "Top 10 home run hitters in 2024"},
        {"role": "assistant", "content": json.dumps({
            "sql": (
                "SELECT b.full_name AS name, b.home_run "
                "FROM batting_stats b "
                "WHERE b.year = 2024 "
                "ORDER BY b.home_run DESC LIMIT 10;"
            ),
            "x": "name", "y": "home_run", "chart_type": "bar", "assumptions": ""
        })},

        # Analyst phrasing: OPS + position filter + sort tie-break
        {"role": "user", "content": "Left-handed batters with OPS above .850 in 2024, sort by HR desc, top 15"},
        {"role": "assistant", "content": json.dumps({
            "sql": (
                "SELECT b.full_name AS name, (b.on_base_percent + b.slg_percent) AS on_base_plus_slg, b.home_run "
                "FROM batting_stats b "
                "JOIN player_profiles p ON p.player_id = b.player_id "
                "WHERE b.year = 2024 AND p.bats = 'L' AND (b.on_base_percent + b.slg_percent) > 0.850 "
                "ORDER BY b.home_run DESC LIMIT 15;"
            ),
            "x": "name", "y": ["on_base_plus_slg","home_run"], "chart_type": "bar",
            "assumptions": "OPS = OBP + SLG."
        })},

        # Per-season line for multiple players using features (aligned joins)
        {"role": "user", "content": "Show 2019–2021 average wOBA_3yr for José Ramírez and Rafael Devers"},
        {"role": "assistant", "content": json.dumps({
            "sql": (
                "SELECT b.year AS year, b.full_name AS name, f.woba_3yr "
                "FROM batting_stats b "
                "JOIN player_features f ON f.player_id = b.player_id AND f.year = b.year "
                "WHERE b.year BETWEEN 2019 AND 2021 "
                "AND b.full_name IN ('José Ramírez','Rafael Devers') "
                "ORDER BY year ASC;"
            ),
            "x": "year", "y": "woba_3yr", "chart_type": "line",
            "assumptions": "Aligned features by player_id AND year."
        })},

        # Position grouping example
        {"role": "user", "content": "Compare 3B vs SS OPS in 2023 for players with >= 300 PA"},
        {"role": "assistant", "content": json.dumps({
            "sql": (
                "SELECT p.primary_position AS pos, AVG(b.on_base_percent + b.slg_percent) AS on_base_plus_slg "
                "FROM batting_stats b "
                "JOIN player_profiles p ON p.player_id = b.player_id "
                "WHERE b.year = 2023 AND b.plate_appearances >= 300 AND p.primary_position IN ('3B','SS') "
                "GROUP BY p.primary_position "
                "ORDER BY on_base_plus_slg DESC;"
            ),
            "x": "pos", "y": "on_base_plus_slg", "chart_type": "bar",
            "assumptions": "OPS = OBP + SLG; grouped by position."
        })},

        # Steer single-player + range to clean per-year line (alias: 'slugging %' → slg_percent)
        {"role": "user", "content": "judge slugging % from 2022 to 2025"},
        {"role": "assistant", "content": json.dumps({
            "sql": (
                "SELECT b.year AS year, b.slg_percent "
                "FROM batting_stats b "
                "WHERE b.full_name ILIKE '%judge%' AND b.year BETWEEN 2022 AND 2025 "
                "ORDER BY year ASC;"
            ),
            "x": "year", "y": "slg_percent", "chart_type": "line", "assumptions": ""
        })},

        {"role": "user", "content": user_text},
    ]


def llm_nl2sql_plan(db, text):
    catalog = build_catalog(db)
    alias_catalog = build_alias_catalog(db, catalog)
    client = get_llm_client()
    if client is None:
        return {
            "sql": (
                "SELECT full_name AS name, home_run "
                "FROM batting_stats WHERE year = 2025 "
                "ORDER BY home_run DESC LIMIT 10;"
            ),
            "x": "name", "y": "home_run", "chart_type": "bar",
            "assumptions": "LLM unavailable; default HR leaderboard."
        }

    # Lightweight hinting: if the prompt contains aliased phrases, surface canonical stats
    tnorm = _normalize_key(text)
    matched = []
    for phrase, col in alias_catalog.items():
        if phrase and phrase in tnorm:
            matched.append(col)
    matched = sorted({m for m in matched})
    user_msg = text if not matched else f"{text}\n\n[canonical_stats={','.join(matched)}]"

    all_messages = fewshot_messages(db, catalog, alias_catalog, user_msg)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=all_messages[0]["content"],
        messages=all_messages[1:],
        temperature=0.0,
    )
    raw_text = (response.content[0].text or "{}").strip()
    return json.loads(raw_text)


# ----------------------- String helpers (no regex) -----------------------
def strip_sql_comments(sql):
    if not isinstance(sql, str):
        return ""
    index = 0
    length = len(sql)
    output_chars = []
    inLine = False
    inBlock = False
    inSingle = False
    inDouble = False
    while index < length:
        ch = sql[index]
        nxt = sql[index + 1] if index + 1 < length else ""

        if not inLine and not inBlock:
            if not inSingle and not inDouble:
                if ch == "'":
                    inSingle = True; output_chars.append(ch); index += 1; continue
                if ch == '"':
                    inDouble = True; output_chars.append(ch); index += 1; continue
                if ch == "-" and nxt == "--":
                    inLine = True; index += 2; continue
                if ch == "/" and nxt == "*":
                    inBlock = True; index += 2; continue
                output_chars.append(ch); index += 1; continue
            else:
                output_chars.append(ch)
                if inSingle and ch == "'" and (index == 0 or sql[index - 1] != "\\"):
                    inSingle = False
                elif inDouble and ch == '"' and (index == 0 or sql[index - 1] != "\\"):
                    inDouble = False
                index += 1; continue

        if inLine:
            if ch == "\n":
                inLine = False; output_chars.append(ch)
            index += 1; continue

        if inBlock:
            if ch == "*" and nxt == "/":
                inBlock = False; index += 2
            else:
                index += 1
            continue
    return "".join(output_chars)


def lstrip_lower(s):
    return (s or "").lstrip().lower()


def tokenize_identifiers(sql):
    tokens, current = [], []
    for ch in sql:
        if ch.isalnum() or ch == "_":
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current)); current = []
    if current:
        tokens.append("".join(current))
    return tokens


# ----------------------- MLB pa/qual helpers (no regex) -----------------------
def extract_years_from_text(text):
    years_found, digits = [], ""
    for ch in str(text or ""):
        if ch.isdigit():
            digits += ch
        else:
            if len(digits) == 4:
                try:
                    year_val = int(digits)
                    if 1900 <= year_val <= 2099:
                        years_found.append(year_val)
                except Exception:
                    pass
            digits = ""
    if len(digits) == 4:
        try:
            year_val = int(digits)
            if 1900 <= year_val <= 2099:
                years_found.append(year_val)
        except Exception:
            pass
    return years_found


def inject_min_pa_condition(sql, pa_column, min_pa):
    sql_string = strip_sql_comments(sql).rstrip()
    hadSemicolon = sql_string.endswith(";")
    if hadSemicolon:
        sql_string = sql_string[:-1]

    lower_sql = sql_string.lower()

    def findToken(token):
        return lower_sql.find(token)

    cut_candidates = [findToken(" group by "), findToken(" having "), findToken(" order by "), findToken(" limit "), findToken(" union ")]
    cut_position = min([i for i in cut_candidates if i != -1] or [len(sql_string)])

    where_position = findToken(" where ")
    condition = f"{pa_column} >= {int(min_pa)}"

    if where_position != -1 and where_position < cut_position:
        sql_string = sql_string[:cut_position] + " AND " + condition + sql_string[cut_position:]
    else:
        sql_string = sql_string[:cut_position] + " WHERE " + condition + " " + sql_string[cut_position:]

    return sql_string + (";" if hadSemicolon else "")


# ----------------------- Safety checks -----------------------
_DENY_KEYWORDS = {
    "insert", "update", "delete", "truncate", "drop", "alter",
    "create", "grant", "revoke"
}

def is_safe_select(sql):
    if not isinstance(sql, str):
        return False
    sql_no_comments = strip_sql_comments(sql)
    if not lstrip_lower(sql_no_comments).startswith("select"):
        return False
    if sql_no_comments.count(";") > 1:
        return False
    tokens = [t.lower() for t in tokenize_identifiers(sql_no_comments)]
    for token in tokens:
        if token in _DENY_KEYWORDS:
            return False
    return True


def next_word(s, start_index):
    length = len(s)
    i = start_index
    while i < length and s[i].isspace():
        i += 1
    buffer_chars = []
    while i < length:
        ch = s[i]
        if ch.isalnum() or ch == "_" or ch == ".":
            buffer_chars.append(ch); i += 1
        else:
            break
    return "".join(buffer_chars)


def tables_in_from_join(sql):
    lowered = strip_sql_comments(sql).lower()
    tables = []
    index = 0
    length = len(lowered)
    while index < length:
        if index + 5 <= length and lowered[index:index+5] == " from ":
            name = next_word(lowered, index + 5)
            if name:
                tables.append(name.split(".")[-1])
            index += 5
        elif index + 6 <= length and lowered[index:index+6] == " join ":
            name = next_word(lowered, index + 6)
            if name:
                tables.append(name.split(".")[-1])
            index += 6
        else:
            index += 1
    seen = set()
    unique_tables = []
    for t in tables:
        if t not in seen:
            unique_tables.append(t); seen.add(t)
    return unique_tables


def whitelist_sql(sql, allowed_tables):
    lowered = strip_sql_comments(sql).lower()
    used_tables = tables_in_from_join(lowered)
    if not used_tables:
        raise ValueError("Query must reference at least one table.")
    for t in used_tables:
        if t not in allowed_tables:
            raise ValueError(f"Table not allowed: {t}")

    needs_year_alignment = any(t in lowered for t in ("player_features", "player_seasons"))
    if " join " in lowered and ("player_id" not in lowered):
        raise ValueError("Join must include player_id equality.")
    if needs_year_alignment and (" year " not in lowered):
        raise ValueError("Joins with features/seasons must align on year as well.")

    if "information_schema" in lowered or "pg_" in lowered:
        raise ValueError("System schemas are not allowed.")


def enforce_limit(sql, max_rows=200):
    sql_clean = strip_sql_comments(sql).strip()
    hasSemicolon = sql_clean.endswith(";")
    if hasSemicolon:
        sql_clean = sql_clean[:-1].rstrip()

    tokens = tokenize_identifiers(sql_clean)
    lowercase_tokens = [t.lower() for t in tokens]
    limit_index = None
    for i, token in enumerate(lowercase_tokens):
        if token == "limit":
            limit_index = i
            break

    if limit_index is None:
        sql_clean = sql_clean + f" LIMIT {max_rows}"
    else:
        if limit_index + 1 < len(tokens):
            try:
                current_limit = int(tokens[limit_index + 1])
                if current_limit > max_rows:
                    for needle in (f"LIMIT {current_limit}", f"limit {current_limit}", f"Limit {current_limit}"):
                        pos = sql_clean.find(needle)
                        if pos == -1:
                            pos = sql_clean.lower().find(needle.lower())
                        if pos != -1:
                            sql_clean = sql_clean[:pos] + f"LIMIT {max_rows}" + sql_clean[pos + len(needle):]
                            break
            except Exception:
                sql_clean = sql_clean + f" /* limit parse failed; capped at {max_rows} server-side */"
        else:
            sql_clean = sql_clean + f" /* missing limit value; capped at {max_rows} server-side */"

    sql_clean = sql_clean.strip()
    if not sql_clean.endswith(";"):
        sql_clean += ";"
    return sql_clean


# ----------------------- Position filtering helpers -----------------------
def filter_disallowed_positions(rows, x_key):
    disallowed = {"OF", "TWP", "TWO-WAY PLAYER", "TWO WAY PLAYER", "IF", "UTIL"}
    kept_rows = []
    removed_count = 0
    for row in rows:
        value = row.get(x_key)
        if isinstance(value, str) and value.strip().upper() in disallowed:
            removed_count += 1
            continue
        kept_rows.append(row)
    return kept_rows, removed_count


# ----------------------- Title & narration helpers -----------------------
def format_number_short(value):
    try:
        number = float(value)
    except Exception:
        return str(value)
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    if abs(number) >= 1:
        return f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{number:.3f}".rstrip("0").rstrip(".")


def detect_context_from_prompt(text):
    t = (text or "").lower()
    context = {}
    if "left" in t or "lefty" in t or "lefties" in t or "bats l" in t:
        context["hand"] = "Left-handed"
    elif "right" in t or "righty" in t or "righties" in t or "bats r" in t:
        context["hand"] = "Right-handed"
    elif "switch" in t or "bats s" in t:
        context["hand"] = "Switch-hitters"

    if "american league" in t or " al " in f" {t} ":
        context["league"] = "American League"
    elif "national league" in t or " nl " in f" {t} ":
        context["league"] = "National League"
    return context


def parse_limit_from_sql(sql):
    no_comments = strip_sql_comments(sql)
    tokens = tokenize_identifiers(no_comments)
    lowercase_tokens = [t.lower() for t in tokens]
    for i, token in enumerate(lowercase_tokens):
        if token == "limit" and i + 1 < len(tokens):
            try:
                return int(tokens[i + 1])
            except Exception:
                return None
    return None


def parse_order_direction_from_sql(sql):
    lowered = strip_sql_comments(sql).lower()
    idx = lowered.find(" order by ")
    if idx == -1:
        return "desc"
    tail = lowered[idx + len(" order by "):]
    if " asc" in tail:
        return "asc"
    if " desc" in tail:
        return "desc"
    return "desc"


def format_year_span(years_list):
    if not years_list:
        return ""
    if len(years_list) == 1:
        return f"{years_list[0]}"
    return f"{years_list[0]}–{years_list[1]}"


def build_title(text, x_key, y_key, sql):
    if isinstance(y_key, str) and y_key:
        y_label = stat_label(y_key)
    elif isinstance(y_key, list) and y_key:
        y_label = ", ".join([stat_label(s) for s in y_key])
    else:
        y_label = None

    years_list = extract_years_from_text(text)
    year_part = format_year_span(years_list)
    context = detect_context_from_prompt(text)
    limit_value = parse_limit_from_sql(sql)
    order_direction = parse_order_direction_from_sql(sql)

    parts = []

    x_lower = (str(x_key or "")).lower()
    looks_like_leaderboard = x_lower in ("name", "full_name", "player", "player_name")
    if looks_like_leaderboard and isinstance(limit_value, int) and limit_value > 0 and y_label:
        dir_word = "Top" if order_direction != "asc" else "Lowest"
        parts.append(f"{dir_word} {limit_value} {y_label}")
    elif y_label:
        if x_lower in ("pos", "position", "primary_position"):
            parts.append(f"{y_label} by Position")
        elif x_lower in ("year", "season"):
            parts.append(f"{y_label} by Year")
        else:
            parts.append(y_label)

    qualifiers = []
    if "hand" in context:
        qualifiers.append(context["hand"])
    if "league" in context:
        qualifiers.append(context["league"])
    if qualifiers:
        parts.append(", ".join(qualifiers))

    if year_part:
        parts.append(year_part)

    return " — ".join([p for p in parts if p])


def analyst_noun_for(stat_slug):
    if stat_slug == "home_run":
        return "HR"
    if stat_slug == "on_base_plus_slg":
        return "OPS"
    if stat_slug == "on_base_percent":
        return "OBP"
    if stat_slug == "slg_percent":
        return "SLG"
    if stat_slug == "woba":
        return "wOBA"
    return stat_label(stat_slug)


def build_summary(chart_type, series, x_key, y_key, prompt_text):
    """Single-sentence conclusion that considers ALL series (not just the first)."""
    if isinstance(y_key, str):
        stat_slug = y_key
    elif isinstance(y_key, list) and y_key:
        stat_slug = y_key[0]
    else:
        stat_slug = None
    stat_name = analyst_noun_for(stat_slug) if stat_slug else "value"

    all_pts = []
    for s in (series or []):
        sid = s.get("id")
        for p in (s.get("data") or []):
            if p.get("y") is None:
                continue
            try:
                all_pts.append({"id": sid, "x": p.get("x"), "y": float(p["y"])})
            except Exception:
                pass

    if not all_pts:
        return "No results."

    best = max(all_pts, key=lambda r: r["y"])
    leaders = [r for r in all_pts if abs(r["y"] - best["y"]) <= 1e-12]
    names = sorted({str(r["id"]) for r in leaders if r.get("id")}) or [str(best.get("x"))]

    years = extract_years_from_text(prompt_text)
    if len(years) == 1:
        yr_phrase = f" for {years[0]}"
    elif len(years) >= 2:
        yr_phrase = f" for {years[0]}–{years[-1]}"
    else:
        yr_phrase = ""

    val_txt = format_number_short(best["y"])
    if len(names) == 1:
        who = names[0]
        return f"{who} posted the highest {stat_name}{yr_phrase} at {val_txt}."
    else:
        return f"{', '.join(names)} tied for the highest {stat_name}{yr_phrase} at {val_txt}."


# ----------------------- Execute & shape -----------------------
def run_nl2sql(db, text):
    plan = llm_nl2sql_plan(db, text)

    sql = str(plan.get("sql") or "").strip()
    if not sql:
        raise ValueError("Planner produced no SQL.")

    if not is_safe_select(sql):
        raise ValueError("Unsafe SQL; only single SELECT statements are allowed.")

    whitelist_sql(sql, ALLOWED_TABLES)
    sql = enforce_limit(sql, 200)

    years_list = extract_years_from_text(text)
    single_year_for_qualification = years_list[0] if len(years_list) == 1 else None

    y_key = plan.get("y")
    y_columns = y_key if isinstance(y_key, list) else [y_key]
    y_columns = [str(c) for c in y_columns if c]

    wantsRateQualification = any(is_rate_stat(col) for col in y_columns)
    plateAppearanceColumnName = _pa_column_name(db)

    qualificationInfo = None
    if single_year_for_qualification is not None and wantsRateQualification and plateAppearanceColumnName:
        min_pa = _qualified_pa_threshold(int(single_year_for_qualification))
        sql = inject_min_pa_condition(sql, plateAppearanceColumnName, min_pa)
        qualificationInfo = {
            "min_pa": int(min_pa),
            "pa_column": plateAppearanceColumnName,
            "rule": "MLB 3.1 PA per scheduled game (Rule 9.22)",
            "year": int(single_year_for_qualification),
        }

    rows = db.execute(sa_text(sql)).mappings().all()

    x_key = plan.get("x")
    y_key = plan.get("y")
    chart_type = (plan.get("chart_type") or "bar").lower()
    assumptions = (plan.get("assumptions") or "").strip()

    if not rows:
        return {
            "chart_type": "bar",
            "series": [{"id": "empty", "data": []}],
            "narration": "No results.",
            "meta": {"title": build_title(text, plan.get("x"), plan.get("y"), sql)}
        }

    xKeyLowercase = (str(x_key or "")).lower()
    looksLikePositionXAxis = xKeyLowercase in ("pos", "position", "primary_position")
    removedPositions = 0
    if looksLikePositionXAxis:
        rows, removedPositions = filter_disallowed_positions(rows, x_key)

    def toFloat(value):
        try:
            return float(value)
        except Exception:
            return None

    # if the rows include a player name and X is year/season, build one series per player
    name_key = None
    if rows and isinstance(rows[0], dict):
        for cand in ("name", "full_name", "player", "player_name"):
            if cand in rows[0]:
                name_key = cand
                break

    is_year_axis = str(x_key or "").lower() in ("year", "season")

    if name_key and is_year_axis and isinstance(y_key, str):
        groups = {}
        for row in rows:
            nm = row.get(name_key)
            xv = row.get(x_key)
            yf = toFloat(row.get(y_key))
            if nm is None or xv is None or yf is None:
                continue
            groups.setdefault(nm, {})
            groups[nm][xv] = {"x": xv, "y": yf}

        series = []
        for nm, by_year in groups.items():
            ordered = sorted(by_year.values(), key=lambda p: p["x"])
            series.append({"id": nm, "data": ordered})

        meta = {
            "title": build_title(text, x_key, y_key, sql),
            "y_label": stat_label(y_key),
        }
    else:
        series = []
        if isinstance(y_key, list):
            for ycol in y_key:
                points = []
                for row in rows:
                    xv = row.get(x_key)
                    yf = toFloat(row.get(ycol))
                    if xv is not None and yf is not None:
                        points.append({"x": xv, "y": yf})
                series.append({"id": ycol, "data": points})
            meta = {"label_map": label_map_for(y_key), "title": build_title(text, x_key, y_key, sql)}
        else:
            points = []
            for row in rows:
                xv = row.get(x_key)
                yf = toFloat(row.get(y_key))
                if xv is not None and yf is not None:
                    points.append({"x": xv, "y": yf})
            series = [{"id": y_key, "data": points}]
            meta = {"label_map": label_map_for([y_key]), "title": build_title(text, x_key, y_key, sql)}
            if isinstance(y_key, str) and y_key:
                meta["y_label"] = stat_label(y_key)

    if qualificationInfo:
        meta["qualifier"] = qualificationInfo

    if looksLikePositionXAxis and removedPositions > 0:
        meta.setdefault("filters", {})
        meta["filters"]["positions_excluded"] = ["OF", "TWP", "IF", "UTIL"]

    narration = build_summary(
        chart_type=chart_type,
        series=series,
        x_key=x_key,
        y_key=y_key,
        prompt_text=text,
    )

    return {
        "chart_type": chart_type,
        "series": series,
        "narration": narration,
        "meta": meta,
    }
