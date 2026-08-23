# SaberGraphs

Ask baseball questions in plain English. Get real charts back.

```
"compare Volpe and Judge home runs in their rookie seasons"
"lowest ERA in 2024, minimum 150 innings"
"fastest average bat speed in 2025, minimum 100 competitive swings"
```

The interesting part is what happens in between: **the AI never generates a
number.** It identifies the players and stats you mean (and asks you to pick
when a name is ambiguous), then either writes a single SQL query that a
safety layer validates before a read-only database role executes it, or runs
built-in analytics like Marcel projections and rookie-season alignment.
Every value on every chart comes out of PostgreSQL.

**Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL, React, Nivo, Docker,
pandas, NumPy, scikit-learn, Anthropic Claude API. Backend on Render,
frontend on Vercel.

---

## How a question is answered

```
POST /api/prompt { text, hints? }
 1. Identify players and stats (no LLM): exact-token matching against the
    local database, the Chadwick register, and the MLB Stats API as an
    identity fallback. Ambiguous name or missing stat -> the API returns a
    "clarify" payload with clickable options instead of guessing.
 2. Pick the tool:
    - rookie / career-aligned asks  -> SQL window-function view + toolkit
    - forecasts                     -> Marcel projections (backtested)
    - clarified queries             -> deterministic SQL, zero LLM calls
    - everything else               -> Claude drafts one SELECT
 3. Guard every generated query: single statement, leading SELECT,
    8-relation allowlist, comment/quoting tricks rejected, hard LIMIT cap,
    then execute as a SELECT-only Postgres role with a 5s timeout.
 4. Return the canonical payload: { chart_type, series, narration, meta,
    ai_source } and render with Nivo.
```

Every response tags which path answered (`ai_source`): `nl2sql`,
`sql_fallback`, `agent`, `toolkit`, `deterministic`, or `preflight`.

```mermaid
flowchart LR
    Q["You ask a question"] --> PRE["Preflight resolves\nplayers + stats\n(asks if unclear)"]
    PRE --> PLAN{"Pick the tool"}
    PLAN -- "writes one SELECT" --> GUARD["SQL guard\n+ read-only role"]
    PLAN -- "built-in analytics" --> TOOL["Toolkit\nprojections, alignment"]
    GUARD --> DB[("PostgreSQL\nbatting, pitching,\nStatcast bat tracking")]
    TOOL --> DB
    DB --> CHART["Chart + plain\nEnglish summary"]
```

---

## Engineering highlights

### The SQL safety layer

An LLM writing SQL against a live database is the riskiest part of this
design, so it is one isolated, dependency-free module
(`backend/app/agent/sql_guard.py`) that lexes every candidate statement:
string-aware comment stripping, literal masking, single-statement
enforcement, a leading-SELECT allowlist, an 8-relation table allowlist,
join-alignment rules, and a hard row cap. Whatever passes still executes as
a dedicated `nl2sql_ro` Postgres role: SELECT-only grants, read-only
transactions, 5 second statement timeout. The raw ingestion tables are
deliberately not on the allowlist.

Before making this public I audited my own code and found a whitelist
bypass: the table extractor compared a 5-character slice against the
6-character string `" from "`, so FROM tables were never checked. The fix
is a real tokenizer, and the regression suite is 69 tests including 42
adversarial SQL-injection payloads (`tests/backend/test_sql_guard.py`).

### Entity resolution that asks instead of guessing

"muncy" matches two different Max Muncys. "lombard jr" is a 2026 call-up
who is not in the data at all. The resolver matches exact tokens (never
substrings, so "lombard" can never match Lombardozzi), classifies every
player as batter, pitcher, or two-way from their own AB and innings
volumes, and falls back to the MLB Stats API for identity only. When a
name or stat is genuinely ambiguous the API returns clickable options, and
the follow-up request runs deterministically with zero LLM involvement.
Unanswerable asks fail honestly: "Unable to chart George Lombard Jr. (MLB
debut 2026-08-04, New York Yankees), no batting data for him in this
dataset, which covers 2015 to 2025."

### Rookie seasons computed in SQL, not guessed

"Rookie season" is a database column, not an LLM opinion. A window-function
view (`player_season_index`) tracks career at-bats entering each season and
applies the rookie-eligibility rule, so Aaron Judge's rookie year resolves
to 2017 (52 HR), not his 4-HR 2016 cup of coffee, and players who debuted
before the data begins are flagged rather than faked. Comparisons across
different years label each bar with the player's own season: "Aaron Judge
(2017)" next to "Anthony Volpe (2023)".

### A real ingestion pipeline

`data_pipeline/ingest/` landed 3.85M Statcast pitches (2021 to 2025) in a
resumable overnight backfill: idempotent `INSERT ... ON CONFLICT` upserts,
a watermark table where each chunk's rows and completion marker commit in
one transaction (kill -9 safe), per-chunk data-quality gates, and a frozen
schema manifest with Alembic migrations. The quality gates caught a real
bug on day one: the Chadwick register encodes "no MLB id" as the sentinel
-1, which tripped the duplicate-key threshold instead of silently
corrupting the ID crosswalk. Measured proof of idempotency: 3,953,709 rows
upserted across all chunks, 3,846,144 distinct rows in the table, and the
107,565-row difference is exactly the deliberately overlapping windows,
written twice with zero duplicates.

### Forecasts that report their own accuracy

Marcel projections (5/4/3 recency weighting, league-mean regression, age
adjustment) are evaluated with a season-holdout backtest: train through
season N-1, predict season N, for 2022 to 2025 (n = 1,324 player-seasons).

| System | wOBA RMSE | HR RMSE |
|---|---|---|
| Naive repeat last season | 0.0484 | 8.98 |
| Trailing 3-year mean | 0.0455 | 8.45 |
| **Marcel** | **0.0336** | **7.40** |
| KNN-aging (this repo's fancier model) | 0.0499 | 10.97 |

The simple model won, so it is the default. The KNN model's own
uncertainty bands measured roughly 47% empirical coverage against a
nominal 80%, so the API labels them experimental and ships the measured
calibration with every response instead of hiding it. Full tables:
[docs/BACKTEST.md](docs/BACKTEST.md).

---

## The data

All charted data lives in the app's own PostgreSQL database. The MLB Stats
API is used only to identify players.

| Table | Rows | Coverage |
|---|---|---|
| `batting_stats` | 7,375 player-seasons | 2015 to 2025 |
| `pitching_stats` | 8,264 player-seasons (2,263 pitchers) | 2015 to 2025 |
| `mart_bat_tracking_season` | 1,321 player-seasons | 2024 to 2025 (bat tracking began in 2024) |
| `mart_batter_pitch_season` | 3,722 player-seasons | 2021 to 2025, aggregated from pitches |
| `raw_statcast_pitches` | 3,846,144 pitches | 2021 to 2025 |
| `raw_chadwick_people` | 24,818 people | MLBAM / FanGraphs / BBRef / Retrosheet ID crosswalk |
| `player_season_index` | view | career season number + rookie flags |
| `player_directory` | cache | positions / teams from the MLB Stats API |

---

## Quick start

Prereqs: Docker Desktop. Python 3.11 on the host only for the data loaders.

```bash
git clone https://github.com/cmartinez131/sabermetric-ai.git
cd sabermetric-ai
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for the LLM paths
docker compose up --build
# backend http://localhost:8000 (docs at /docs), frontend http://localhost:3000
```

Everything boots with no `.env` and no API key (rule-based fallbacks), but
the app is empty until you load data:

```bash
# 1) Pitch-level pipeline (own venv; pybaseball pins an older pandas)
python3 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r data_pipeline/requirements.txt
export DATABASE_URL="postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db"
.venv-pipeline/bin/alembic upgrade head
.venv-pipeline/bin/python -m data_pipeline.ingest.cli backfill-all   # ~3h, resumable

# 2) Season-level batting + pitching CSVs (Savant custom leaderboard exports,
#    2015-2025, saved into data_pipeline/data/ -- not redistributed here)
python data_pipeline/scripts/load_batters.py
python data_pipeline/scripts/load_pitchers.py
python data_pipeline/scripts/fetch_player_profiles.py
```

macOS note: a local Postgres on port 5432 silently shadows the Docker one
and the loaders fail with `role "user" does not exist`. Stop it
(`brew services stop postgresql@14`) or point `DATABASE_URL` at a
non-loopback interface.

### Try it

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"compare volpe and judge home runs in their rookie seasons"}' | jq
# -> bars labeled "Anthony Volpe (2023)" and "Aaron Judge (2017)", ai_source "toolkit"

curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"muncy vs judge home runs in 2025"}' | jq '.clarification'
# -> chart_type "clarify": two Max Muncys to choose from, as clickable options

curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"lowest ERA in 2024, minimum 150 innings"}' | jq '.narration'
# -> "Chris Sale posted the lowest ERA for 2024 at 2.38."
```

---

## Tests

```bash
python -m pytest tests/ -v          # backend + pipeline, no database needed
ruff check backend tests data_pipeline db
cd frontend && npx eslint src --ext .js,.jsx --max-warnings=0 && CI=true npm test
```

**186 backend/pipeline tests + 11 frontend tests, all passing.** Highlights:
69 SQL-guard tests (42 adversarial injection payloads), rookie-eligibility
rule tests (the Judge case, censoring), entity-resolution tests (suffix
handling, the Lombardozzi substring trap, two-Muncy ambiguity), backtest
leakage guards, and pipeline chunking / watermark-resume / upsert-idempotency
tests. CI runs the same commands on every push.

---

## Configuration

Every variable has a working default; `.env` is optional.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://user:password@db:5432/baseball_db` | host loaders use the `127.0.0.1` form |
| `ANTHROPIC_API_KEY` | none | optional; rule-based fallbacks without it |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | |
| `NL2SQL_RO_USER` / `NL2SQL_RO_PASSWORD` | `nl2sql_ro` | the SELECT-only role; change for real deployments |
| `CORS_ALLOW_ORIGINS` | unset (`*`) | set explicitly in production |

---

## Limitations

Written down because they are true.

- **Data ends with the 2025 season.** The 2026 season is not loaded yet;
  out-of-range questions get an explicit coverage message, and the pipeline
  supports extending the range.
- **KNN aging bands are experimental.** Their measured coverage (~47% vs a
  nominal 80%) ships in the payload; residual-based replacements are open
  work.
- **Rookie alignment covers batters only.** Pitcher rookie eligibility (the
  50-inning rule) is not modeled; pitcher rookie asks get an honest refusal
  with a suggested alternative.
- **Bat tracking is young.** Two seasons exist league-wide (2024, 2025), so
  no swing-metric trend deserves much confidence.
- **The 2020 COVID season is used at face value** in trailing windows and
  Marcel weights.
- **Development posture.** Compose mounts source with reload, CORS defaults
  open, and there is no auth or rate limiting. Not a multi-tenant deploy.

---

## Data sources and attribution

Personal, non-commercial portfolio project. Not affiliated with MLB.

- **Baseball Savant / MLB Advanced Media**: Statcast pitch data, bat
  tracking, and the season CSV exports ([MLB terms](http://gdx.mlb.com/components/copyright.txt)).
  The CSVs are not redistributed in this repo.
- **MLB Stats API**: player identity and profile metadata.
- **[pybaseball](https://github.com/jldbc/pybaseball)** (MIT): Statcast and
  Chadwick fetchers.
- **[Chadwick Bureau Register](https://github.com/chadwickbureau/register)**
  (CC BY-SA 4.0): the player ID crosswalk; derived tables carry the same
  license. The register includes Retrosheet IDs: "The information used here
  was obtained free of charge from and is copyrighted by Retrosheet.
  Interested parties may contact Retrosheet at www.retrosheet.org."
- Marcel is Tom Tango's method; the implementation here is my own.

## License

No license granted yet, all rights reserved pending a decision. Third-party
data retains its own terms.
