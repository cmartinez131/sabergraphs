# backend/app/agent/nl2sql.py

"""
Schema-aware NL → SQL for Sabermetric AI

Supports:
- Filters & joins across: batting_stats, player_profiles, player_features, player_seasons
- Year alignment rules (features & seasons require player_id AND year)
- OPS computed as (on_base_percent + slg_percent) AS on_base_plus_slg
- SELECT-only, single statement, LIMIT cap, table whitelist

PLUS:
- MLB Rule 9.22: auto-qualify RATE stat leaderboards by adding a PA threshold
  when the prompt implies a single-season rate leaderboard (e.g., "highest OPS in 2023").
- Position cleanup: when the X-axis is a position field, exclude "TWP"/"Two-Way Player",
  the aggregate "OF", and utility buckets like "IF"/"UTIL".

Returns canonical payload:
  { chart_type, series, narration, meta? }
compatible with your chart renderer.
"""

import os
import json

from sqlalchemy import text as sa_text
from sqlalchemy import inspect as sa_inspect

from ..toolkit.stats import table_columns, label_map_for
from ..db.models import BattingStats

from ..toolkit.stats import (
    stat_label,
    is_rate_stat,
    _pa_column_name,
    _qualified_pa_threshold,
)

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

ALLOWED_TABLES = {
    "batting_stats",
    "player_profiles",
    "player_features",
    "player_seasons",
}

# ----------------------- LLM wrapper -----------------------
def getLlmClient():
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None


def reflectTableColumns(db, table_name):
    try:
        inspector = sa_inspect(db.bind)
        columns = inspector.get_columns(table_name)
        return [c["name"] for c in columns]
    except Exception:
        return []


def buildCatalog(db):
    catalog = {
        "batting_stats": sorted(table_columns(db)),
        "player_profiles": reflectTableColumns(db, "player_profiles"),
        "player_features": reflectTableColumns(db, "player_features"),
        "player_seasons": reflectTableColumns(db, "player_seasons"),
    }
    if "on_base_plus_slg" not in catalog["batting_stats"]:
        catalog["batting_stats"] = sorted(set(catalog["batting_stats"]) | {"on_base_plus_slg"})
    return catalog


def buildSchemaPrompt(catalog):
    def joinColumns(table_name):
        columns = ", ".join(sorted(catalog.get(table_name, [])))
        return f"{table_name}({columns})"
    schema_lines = [joinColumns(t) for t in ALLOWED_TABLES]
    schema_block = "\n".join(schema_lines)

    return f"""
You write ONE safe Postgres SELECT over these tables; alias projected fields to simple names:

{schema_block}

Join rules:
- ALWAYS join on player_id when combining tables.
- If joining player_features or player_seasons with batting_stats, also join on year
  (i.e., both player_id AND year). Example:
    FROM batting_stats b
    JOIN player_features f ON f.player_id = b.player_id AND f.year = b.year
- player_profiles is per-player; join on player_id only.
- Compute OPS as (on_base_percent + slg_percent) AS on_base_plus_slg when needed.

Constraints:
- Output JSON only, no prose.
- SELECT-only. No DDL/DML.
- Reference only these tables and their columns.
- Alias columns used in the response to simple names that match your JSON "x"/"y".
- If user gives a single year: WHERE <table>.year = YYYY.
- For ranges: WHERE <table>.year BETWEEN Y1 AND Y2.
- When ranking, include ORDER BY and LIMIT (default LIMIT 50 if user doesn't say).
- Chart types: choose "bar" (categorical x) or "line" (time series).

Return JSON:
{{
  "sql": "SELECT ...",
  "x": "x_axis_column",
  "y": "y_axis_column_or_list",
  "chart_type": "bar|line",
  "assumptions": "short note if any"
}}
""".strip()


def fewshotMessages(catalog, user_text):
    return [
        {"role": "system", "content": buildSchemaPrompt(catalog)},
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
        {"role": "user", "content": user_text},
    ]


def llmNl2sqlPlan(db, text):
    catalog = buildCatalog(db)
    client = getLlmClient()
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

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=fewshotMessages(catalog, text),
        temperature=0.0,
    )
    raw_text = (response.choices[0].message.content or "{}").strip()
    return json.loads(raw_text)


# ----------------------- String helpers (no regex) -----------------------
def stripSqlComments(sql):
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


def lstripLower(s):
    return (s or "").lstrip().lower()


def tokenizeIdentifiers(sql):
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
def extractYearsFromText(text):
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


def injectMinPaCondition(sql, pa_column, min_pa):
    sql_string = stripSqlComments(sql).rstrip()
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
    sql_no_comments = stripSqlComments(sql)
    if not lstripLower(sql_no_comments).startswith("select"):
        return False
    if sql_no_comments.count(";") > 1:
        return False
    tokens = [t.lower() for t in tokenizeIdentifiers(sql_no_comments)]
    for token in tokens:
        if token in _DENY_KEYWORDS:
            return False
    return True


def nextWord(s, start_index):
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


def tablesInFromJoin(sql):
    lowered = stripSqlComments(sql).lower()
    tables = []
    index = 0
    length = len(lowered)
    while index < length:
        if index + 5 <= length and lowered[index:index+5] == " from ":
            name = nextWord(lowered, index + 5)
            if name:
                tables.append(name.split(".")[-1])
            index += 5
        elif index + 6 <= length and lowered[index:index+6] == " join ":
            name = nextWord(lowered, index + 6)
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


def whitelistSql(sql, allowed_tables):
    lowered = stripSqlComments(sql).lower()
    used_tables = tablesInFromJoin(lowered)
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


def enforceLimit(sql, max_rows=200):
    sql_clean = stripSqlComments(sql).strip()
    hasSemicolon = sql_clean.endswith(";")
    if hasSemicolon:
        sql_clean = sql_clean[:-1].rstrip()

    tokens = tokenizeIdentifiers(sql_clean)
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
def filterDisallowedPositions(rows, x_key):
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
def formatNumberShort(value):
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


def detectContextFromPrompt(text):
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


def parseLimitFromSql(sql):
    no_comments = stripSqlComments(sql)
    tokens = tokenizeIdentifiers(no_comments)
    lowercase_tokens = [t.lower() for t in tokens]
    for i, token in enumerate(lowercase_tokens):
        if token == "limit" and i + 1 < len(tokens):
            try:
                return int(tokens[i + 1])
            except Exception:
                return None
    return None


def parseOrderDirectionFromSql(sql):
    lowered = stripSqlComments(sql).lower()
    idx = lowered.find(" order by ")
    if idx == -1:
        return "desc"
    tail = lowered[idx + len(" order by "):]
    if " asc" in tail:
        return "asc"
    if " desc" in tail:
        return "desc"
    return "desc"


def formatYearSpan(years_list):
    if not years_list:
        return ""
    if len(years_list) == 1:
        return f"{years_list[0]}"
    return f"{years_list[0]}–{years_list[1]}"


def buildTitle(text, x_key, y_key, sql):
    if isinstance(y_key, str) and y_key:
        y_label = stat_label(y_key)
    elif isinstance(y_key, list) and y_key:
        y_label = ", ".join([stat_label(s) for s in y_key])
    else:
        y_label = None

    years_list = extractYearsFromText(text)
    year_part = formatYearSpan(years_list)
    context = detectContextFromPrompt(text)
    limit_value = parseLimitFromSql(sql)
    order_direction = parseOrderDirectionFromSql(sql)

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


def analystNounFor(stat_slug):
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


def buildSummary(chart_type, series, x_key, y_key, prompt_text):
    """
    Produce a single-sentence conclusion about what's shown.
    Examples:
      "DH had the highest OPS for 2025 at 0.803."
      "RF and DH tied for the highest OPS for 2025 at 0.803."
    """
    # Determine primary stat
    if isinstance(y_key, str):
        stat_slug = y_key
    elif isinstance(y_key, list) and y_key:
        stat_slug = y_key[0]
    else:
        stat_slug = None

    stat_name = analystNounFor(stat_slug) if stat_slug else "value"

    # No data?
    if not series or not series[0].get("data"):
        return "No results."

    points = [p for p in series[0]["data"] if p.get("y") is not None]
    if not points:
        return "No results."

    # Find leaders (handle ties)
    max_val = max(float(p["y"]) for p in points)
    eps = 1e-12
    leaders = [str(p["x"]) for p in points if abs(float(p["y"]) - max_val) <= eps]

    # Year phrase from the prompt
    years = extractYearsFromText(prompt_text)
    if len(years) == 1:
        year_phrase = f" for {years[0]}"
    elif len(years) >= 2:
        year_phrase = f" for {years[0]}–{years[-1]}"
    else:
        year_phrase = ""

    value_text = formatNumberShort(max_val)

    if len(leaders) == 1:
        return f"{leaders[0]} had the highest {stat_name}{year_phrase} at {value_text}."
    else:
        leaders_text = ", ".join(leaders)
        return f"{leaders_text} tied for the highest {stat_name}{year_phrase} at {value_text}."


# ----------------------- Execute & shape -----------------------
def run_nl2sql(db, text):
    plan = llmNl2sqlPlan(db, text)

    sql = str(plan.get("sql") or "").strip()
    if not sql:
        raise ValueError("Planner produced no SQL.")

    if not is_safe_select(sql):
        raise ValueError("Unsafe SQL; only single SELECT statements are allowed.")

    whitelistSql(sql, ALLOWED_TABLES)
    sql = enforceLimit(sql, 200)

    years_list = extractYearsFromText(text)
    single_year_for_qualification = years_list[0] if len(years_list) == 1 else None

    y_key = plan.get("y")
    y_columns = y_key if isinstance(y_key, list) else [y_key]
    y_columns = [str(c) for c in y_columns if c]

    wantsRateQualification = any(is_rate_stat(col) for col in y_columns)
    plateAppearanceColumnName = _pa_column_name(db)

    qualificationInfo = None
    if single_year_for_qualification is not None and wantsRateQualification and plateAppearanceColumnName:
        min_pa = _qualified_pa_threshold(int(single_year_for_qualification))
        sql = injectMinPaCondition(sql, plateAppearanceColumnName, min_pa)
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
            "meta": {"title": buildTitle(text, plan.get("x"), plan.get("y"), sql)}
        }

    xKeyLowercase = (str(x_key or "")).lower()
    looksLikePositionXAxis = xKeyLowercase in ("pos", "position", "primary_position")
    removedPositions = 0
    if looksLikePositionXAxis:
        rows, removedPositions = filterDisallowedPositions(rows, x_key)

    def toFloat(value):
        try:
            return float(value)
        except Exception:
            return None

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
        meta = {"label_map": label_map_for(y_key), "title": buildTitle(text, x_key, y_key, sql)}
    else:
        points = []
        for row in rows:
            xv = row.get(x_key)
            yf = toFloat(row.get(y_key))
            if xv is not None and yf is not None:
                points.append({"x": xv, "y": yf})
        series = [{"id": y_key, "data": points}]
        meta = {"label_map": label_map_for([y_key]), "title": buildTitle(text, x_key, y_key, sql)}

    if isinstance(y_key, str) and y_key:
        meta["y_label"] = stat_label(y_key)

    if qualificationInfo:
        meta["qualifier"] = qualificationInfo

    if looksLikePositionXAxis and removedPositions > 0:
        meta.setdefault("filters", {})
        meta["filters"]["positions_excluded"] = ["OF", "TWP", "IF", "UTIL"]

    narration = buildSummary(
        chart_type=chart_type,
        series=series,
        x_key=x_key,
        y_key=y_key,
        prompt_text=text,
    )
    if assumptions:
        # You asked for a conclusion-only summary, so we do not append assumptions.
        pass

    return {
        "chart_type": chart_type,
        "series": series,
        "narration": narration,
        "meta": meta,
    }

# Example usage:
# result = run_nl2sql(db, "Top 10 home run hitters in 2024")
