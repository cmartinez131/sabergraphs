# Sabermetric AI

A baseball data platform with a natural-language front door.

You type *"fastest average bat speed in 2025, minimum 100 competitive swings"* and get a
chart back. The interesting part is what happens in between: **the language model never
produces a number.** It does exactly one of two things — pick a toolkit function and its
arguments, or draft a single `SELECT` — and in the second case that statement is parsed,
validated, rewritten, and executed by a Postgres role that has no permission to do anything
but read six specific tables. Every value the user sees came out of the database.

That constraint is the design. The rest of the system exists to make it hold: a resumable
ingestion pipeline that lands ~3.85M Statcast pitches idempotently, a layered schema that
keeps the raw landing zone invisible to the query planner, a typed API contract, and a
forecast harness that reports its own accuracy honestly enough to say the fancier model
lost.

```
                     ┌──────────────────────────────────────┐
   "bat speed vs     │  LLM: picks a tool, or drafts SQL    │   never returns data
    wOBA in 2025" ──▶│  ──────────────────────────────────  │──┐
                     │  no numbers ever originate here      │  │
                     └──────────────────────────────────────┘  │
                                                               ▼
                              guard_sql() ──▶ nl2sql_ro role ──▶ Postgres ──▶ chart
```

**Stack:** FastAPI · SQLAlchemy · Postgres 13 · Alembic · pandas/NumPy/scikit-learn ·
React + Nivo · Docker Compose · GitHub Actions · Anthropic Claude (optional — the app
degrades to rule-based parsing without a key).

**Repo:** <https://github.com/cmartinez131/sabermetric-ai>

---

## Contents

- [Architecture](#architecture)
- [Layer 1 — the ingestion pipeline](#layer-1--the-ingestion-pipeline)
- [Layer 2 — the database](#layer-2--the-database)
- [Layer 3 — the backend](#layer-3--the-backend)
  - [The SQL guard](#the-sql-guard)
  - [The toolkit and the canonical payload](#the-toolkit-and-the-canonical-payload)
- [Layer 4 — the frontend](#layer-4--the-frontend)
- [Forecasting: Marcel, and a backtest that says so](#forecasting-marcel-and-a-backtest-that-says-so)
- [Quick start](#quick-start)
- [Demo](#demo)
- [Tests and CI](#tests-and-ci)
- [Configuration](#configuration)
- [Limitations](#limitations)
- [Data sources and attribution](#data-sources-and-attribution)
- [Repo layout](#repo-layout)

---

## Architecture

Four layers. The LLM sits beside them as an interface, not inside them as a data source.

```mermaid
flowchart TB
    subgraph L1["① INGESTION — data_pipeline/ · runs on the host"]
        SRC["Baseball Savant statcast()<br/>Savant bat-tracking leaderboard<br/>Chadwick ID register<br/>MLB StatsAPI · Savant CSV export"]
        RUN["runner.py<br/>plan chunks → claim watermark → fetch<br/>→ quality gate → upsert + mark complete<br/><b>in one transaction</b>"]
        SRC --> RUN
    end

    subgraph L2["② POSTGRES — raw → staging → mart"]
        RAW["<b>raw_*</b> landed as-is<br/>raw_statcast_pitches · 3.85M rows<br/>raw_bat_tracking · raw_chadwick_people"]
        STG["<b>stg_*</b> typed views<br/>regular season only, cleaned"]
        MART["<b>mart_*</b> season grain<br/>mart_batter_pitch_season<br/>mart_bat_tracking_season"]
        CORE["<b>core</b> batting_stats · player_profiles<br/>player_seasons · player_features"]
        SURF{{"<b>the only tables the API may read</b><br/>raw_* and stg_* are not allowlisted"}}
        WM[("ingest_watermarks<br/>one row per chunk")]
        RAW --> STG --> MART --> SURF
        CORE --> SURF
    end

    subgraph L3["③ FASTAPI BACKEND"]
        GUARD["<b>sql_guard.guard_sql()</b><br/>one statement · leading SELECT<br/>table allowlist · LIMIT cap · no pg_*"]
        RO(["<b>nl2sql_ro</b> role<br/>SELECT-only grants · 5s timeout<br/>read-only transactions"])
        TOOL["<b>toolkit/</b><br/>stats · marcel · aging<br/>battracking · projections · backtest"]
        PAY["canonical payload<br/>{chart_type, series, narration, meta, ai_source}"]
        GUARD --> RO --> PAY
        TOOL --> PAY
    end

    subgraph L4["④ REACT FRONTEND"]
        CR["ChartRenderer<br/>switch(chart_type) → Nivo"]
    end

    LLM{{"<b>LLM — interface layer</b><br/>picks a tool + args, or drafts one SELECT<br/>never returns data"}}
    REQ["POST /api/prompt"]

    RUN --> RAW
    RUN -. progress .-> WM
    WM -. resume .-> RUN
    SURF --> RO
    SURF --> TOOL
    REQ --> LLM
    LLM -. "candidate SQL" .-> GUARD
    LLM -. "tool name + args" .-> TOOL
    PAY --> CR
```

**Request flow for `POST /api/prompt`** (`backend/app/api/prompt.py`):

1. `is_baseball_prompt()` — non-baseball text returns an empty payload, no LLM call.
2. Forecast wording (*project / predict / forecast / next season*) skips NL→SQL and goes
   straight to the classic tool-picker agent.
3. Otherwise **NL→SQL**: the planner sees a reflected schema + alias catalog, returns JSON
   with a `sql` field, and that SQL goes through `guard_sql()` and the read-only role.
4. If NL→SQL fails or returns the wrong shape for a known season-range prompt, a
   **deterministic SQL fallback** builds the obvious query with no LLM involved.
5. Last resort: the **classic agent** picks a toolkit function and arguments.

Whichever path runs, the response is the same typed payload and `ai_source` records which
one it was (`nl2sql`, `sql_fallback`, or `agent`).

---

## Layer 1 — the ingestion pipeline

`data_pipeline/ingest/` is a resumable ETL system, not a script. It has run a full
five-season Statcast backfill: **194 chunks, 3,846,144 pitches, 2021-03-15 → 2025-11-01**,
in roughly 3 hours of wall clock against Baseball Savant.

Four properties do the work, and each one is what makes an unattended multi-hour backfill
against a rate-limited public API something you can actually walk away from:

**Idempotent upserts.** Every load is `INSERT … ON CONFLICT (natural key) DO UPDATE`
(`ingest/upsert.py`). Reruns and overlapping windows cannot duplicate rows. This is
measurable in the deployed database, not just asserted:

| | |
|---|---|
| Rows upserted across all chunks (`sum(ingest_watermarks.row_count)`) | 3,953,709 |
| Distinct rows in `raw_statcast_pitches` | 3,846,144 |
| Difference | **107,565** |

Those 107,565 rows are exactly the sum of four chunks whose date windows sit off the
season-aligned grid — an early ad-hoc smoke-test window (`--start 2024-06-03 --end
2024-06-30`) that later overlapped the real backfill. Every one of their rows was written
twice and the table did not grow by a single row.

**Resumable backfill.** `ingest_watermarks` holds one row per `(source, chunk_key)`. A
chunk is claimed `in_progress` before the fetch; the landed rows *and* the `completed`
marker are committed in the **same transaction** (`ingest/runner.py::_process_chunk`), so a
crash — `kill -9` included — leaves either nothing or a fully-marked chunk. Reruns skip
`completed` and redo everything else. One failed chunk does not abort the run: it is
logged, the run continues, the process exits nonzero, and the rerun mops up. That is what
makes an unattended overnight backfill safe.

**Data-quality gates that fail loudly** (`ingest/quality.py`, per chunk):

- natural-key columns must exist in the fetched frame and be 100% non-null;
- in-frame duplicate keys are dropped keeping the last, and hard-fail above 0.5%;
- schema drift — columns present upstream but absent from the frozen manifest — is logged,
  never silently dropped.

The gate has already earned its keep. The Chadwick register load is keyed on `key_mlbam`,
and `pybaseball.chadwick_register()` encodes *"this person has no MLBAM id"* as the
sentinel value `-1` — mostly historical umpires and officials carrying only Retrosheet
ids. Thousands of rows collapsing onto a single natural key tripped the duplicate-key
threshold immediately, instead of quietly upserting a garbage row over itself and leaving a
crosswalk that silently dropped players. The fix is one line in `ingest/sources.py`
(filter to `key_mlbam > 0`) and it is documented there with the reason, which is the point:
the gate turned a silent data-integrity bug into a loud, addressable failure at load time.

**Frozen schema manifest + migrations.** `raw_statcast_pitches` columns are pinned in
`ingest/models.py` and Alembic migration `0001`. New upstream columns require a new
migration — the pipeline will log them and refuse to widen itself. Migrations run as the
compose owner role, and the read-only role's `ALTER DEFAULT PRIVILEGES` grant means any
table a migration creates is automatically `SELECT`-able by the NL→SQL role.

Full pipeline docs, including the load order and the mermaid source→raw→staging→mart
diagram: [`data_pipeline/README.md`](data_pipeline/README.md).

---

## Layer 2 — the database

Three layers, and the boundary between them is a security boundary as much as a modeling
one: **only the mart and core tables are reachable from natural language.** The raw landing
zone and the staging views are not in the guard's allowlist and cannot be named in
LLM-generated SQL at all.

| Layer | Table | Rows | Grain |
|---|---|---|---|
| raw | `raw_statcast_pitches` | 3,846,144 | one pitch |
| raw | `raw_bat_tracking` | 1,321 | Savant leaderboard row |
| raw | `raw_chadwick_people` | 24,818 | person (ID crosswalk) |
| staging | `stg_pitches` / `stg_bat_tracking` / `stg_players` | views | typed, regular season only |
| mart | `mart_batter_pitch_season` | 3,722 | batter × season (2021–2025) |
| mart | `mart_bat_tracking_season` | 1,321 | batter × season (2024–2025) |
| core | `batting_stats` | 7,375 | player × season, 187 columns, 2015–2025 |
| core | `player_profiles` / `player_seasons` | 457 / 1,375 | bio and season metadata |
| ops | `ingest_watermarks` | 197 | chunk progress |

`batting_stats` is the wide Savant export (1,980 distinct players). The ORM explicitly maps
the frequently-used columns and reaches the other ~150 through SQLAlchemy reflection via
`resolve_stat_column()`, so the CSV can grow columns without the ORM growing with it.

---

## Layer 3 — the backend

### The SQL guard

`backend/app/agent/sql_guard.py` is the piece of this repo I would most want to be
questioned about. An LLM writing SQL against a production database is the highest-risk
component here, so it is isolated into a single ~430-line module with no database or
SQLAlchemy dependency — pure string and token analysis, which makes it exhaustively
testable without a fixture.

**Defense layer 1 — the statement is validated before it runs.** `guard_sql()` applies
eleven rules in order, and the ordering matters:

1. Reject backslashes outright (`E'…'` escape obfuscation).
2. Strip comments **string-aware and nesting-aware**, replacing each comment with a single
   space — matching Postgres tokenization, so `SEL/**/ECT` does *not* become `SELECT`.
3. Mask string literals before any keyword scan, so a player named *Grant* cannot
   false-positive the deny list.
4. Reject double quotes and `$` outside literals (quoted-identifier and `$$`-quoting tricks
   the planner never legitimately emits).
5. Exactly one statement — a semicolon may appear only at the very end.
6. The leading keyword must be `SELECT`. **An allowlist, not a denylist.**
7. A deny-keyword set (DDL/DML/session/admin/set-ops/cursors) matched on exact tokens after
   dot-splitting, so snake_case columns like `single`, `double`, and `start_year` can never
   collide with it.
8. Reject `information_schema` and any `pg_*` token.
9. Every table in `FROM`/`JOIN` — including comma-separated lists, aliases, and derived
   tables — must be in `ALLOWED_TABLES` (six tables).
10. Join alignment: joins must equate `player_id`/`batter_mlbam`; joins touching
    `player_features`/`player_seasons` must also align on `year`; joins touching mart
    tables must align on `season`.
11. A hard `LIMIT` cap (200) enforced on the **top-level** statement — a `LIMIT` inside a
    subquery does not satisfy it.

**Defense layer 2 — least privilege at execution.** Guarded SQL never touches the
request's read-write session. It runs through `db.database.readonly_session()` on a
dedicated `nl2sql_ro` role with `SELECT`-only grants, `statement_timeout = 5s`, and
`default_transaction_read_only = on`. Those settings are enforced three independent ways:
role-level GUCs set at provisioning, per-connection `options`, and the grants themselves.
The role is provisioned by `db/init/01-readonly-role.sh` on fresh volumes and idempotently
again at every backend startup, so existing volumes get it too. It **fails closed**: if the
role is missing, NL→SQL errors and falls back to deterministic SQL rather than quietly
executing on the owner connection.

**Defense layer 3 — a bounded surface.** The allowlist exposes six curated tables; the raw
landing zone and staging views are deliberately excluded, so even a perfectly-formed
malicious query has nothing interesting to name. The `LIMIT` cap and the statement timeout
bound the cost of anything that does run.

**What the audit found.** Before making this repo public I audited my own code and found a
whitelist bypass in the original table extractor. It matched `" join "` with a 6-character
slice but matched `" from "` with a **5-character** slice — a comparison that can never be
true. Two consequences:

- Every single-table query (the most common shape by far) reported zero tables and was
  rejected as *"must reference at least one table"* — the primary NL→SQL path was
  effectively dead, silently masked by the fallback chain that quietly answered anyway.
- Because only `JOIN`ed tables were ever detected, **the `FROM` table was never checked
  against the allowlist.** Verified against the old code:
  `SELECT * FROM secret_admin_table s JOIN player_profiles p ON p.player_id = s.player_id`
  passed the whitelist.

The fix replaced substring scanning with a small tokenizer that walks `FROM`/`JOIN`,
comma-separated lists, aliases, and derived tables, and validates *every* name it finds.
The failure mode is the lesson: a silently-swallowed exception turned a security bug into
an invisible one, so `api/prompt.py` now logs every NL→SQL failure before falling back.

**The adversarial suite.** `tests/backend/test_sql_guard.py` — 69 tests, no database
required, run on every push:

| | |
|---|---|
| Adversarial payloads that must be rejected | 42 |
| Legitimate queries that must keep working | 11 |
| Unit tests on the lexer, table extraction, and LIMIT enforcement | 16 |

The adversarial corpus covers multi-statement injection (`SELECT …; SET statement_timeout`,
the original bypass repro), `COPY … TO PROGRAM`, comment-hidden keywords, line/block comment
tricks, non-allowlisted `FROM` **and** `JOIN` tables, `pg_sleep` DoS, `pg_*` and
`information_schema` probes, `UNION` and CTE smuggling, `$$`-quoting, `E''` escapes,
subquery-`LIMIT` evasion, and the raw/staging tables that must stay unreachable now that
the marts are allowlisted.

### The toolkit and the canonical payload

`backend/app/toolkit/` owns the data. Every function returns the same shape, and the
backend — not the frontend — decides the chart type:

```json
{
  "schema_version": "1",
  "chart_type": "bar | line | radar | facet",
  "series": [{ "id": "...", "data": [{ "x": ..., "y": ... }] }],
  "narration": "human-readable summary",
  "meta": { "title": "...", "label_map": {}, "...": "..." },
  "ai_source": "nl2sql | sql_fallback | agent"
}
```

That contract is Pydantic v2 (`api/schemas.py`), wired into every route via
`response_model=`, so FastAPI validates responses on the way out and renders the schema at
`/docs`. `schema_version` is serialized on every response and is bumped when the shape
changes in a way the frontend must react to.

Outside the NL→SQL path there is no dynamic SQL at all: stat selection goes through fixed
column maps and `resolve_stat_column()`, and user-supplied names are bound parameters.
`toolkit/stats.py` is the single source of truth for stat labels and column resolution, and
implements MLB Rule 9.22 plate-appearance qualification for leaderboards.

---

## Layer 4 — the frontend

React + Nivo. `src/components/charts/ChartRenderer.jsx` is one component that switches on
`chart_type` and renders bar / line / radar / faceted charts, including p10–p90 band layers
for projections. It never overrides the backend's choice and never reshapes data —
`src/utils/csv.js` is export-only. Query history is server-backed via `/api/history/*`.

Still Create React App; migrating to Vite was the declared scope cut when the pipeline work
ran long.

---

## Forecasting: Marcel, and a backtest that says so

`toolkit/marcel.py` implements classic Marcel for hitters: 5/4/3 recency weighting over
three seasons, ~1200 PA of league-average ballast regressing toward the mean, an age
adjustment around a peak of 29 (+0.6%/yr below, −0.3%/yr above), and projected playing time
of `0.5·PA[t−1] + 0.1·PA[t−2] + 200`. Nothing was tuned on the test seasons — these are the
published constants.

`toolkit/backtest.py` evaluates it season-holdout: train only on seasons ≤ N−1, predict
season N, for N ∈ {2022, 2023, 2024, 2025}. The KNN-aging system runs with a hard
`max_year = N−1` cutoff threaded through every one of its queries (league curve, comparable
selection, *and* the comparables' future paths) so no system can see the evaluation period.
Eligibility is identical across systems: target-season PA ≥ 200, plus at least one observed
season in the prior 3-year window. n = 1,324 player-seasons.

**Overall accuracy, pooled 2022–2025** (lower is better; full per-season and
per-experience-bucket breakdowns in [`docs/BACKTEST.md`](docs/BACKTEST.md)):

| System | wOBA RMSE | wOBA MAE | HR RMSE | HR MAE |
|---|---|---|---|---|
| Naive repeat (last season) | 0.0484 | 0.0356 | 8.98 | 6.74 |
| Trailing mean (3yr) | 0.0455 | 0.0340 | 8.45 | 6.34 |
| **Marcel** | **0.0336** | **0.0268** | **7.40** | **5.64** |
| KNN-aging | 0.0499 | 0.0368 | 10.97 | 7.93 |

**Marcel beat the KNN-aging method**, and not narrowly — KNN finished *behind naively
repeating last season* on both stats. A 1970s-vintage weighted average with a ballast term
outperformed the more elaborate comparable-player model this repo had already built. So
Marcel is now the default for `/api/predict`, and KNN is labeled experimental rather than
quietly retired, because the harness — not the flattering result — is the deliverable.

**Calibration is worse than the point estimates, and that matters more.** Nominal 80% bands
should contain the actual outcome 80% of the time:

| Band | Stat | Empirical coverage | n |
|---|---|---|---|
| KNN-aging, **the model's own p10–p90 output** | Home runs | **48.7%** | 1,324 |
| KNN-aging, **the model's own p10–p90 output** | wOBA | **47.1%** | 1,324 |
| Out-of-sample residual band, Marcel | Home runs | 84.5% | 1,324 |
| Out-of-sample residual band, Marcel | wOBA | 81.4% | 1,324 |
| Out-of-sample residual band, trailing mean | wOBA | 79.5% | 1,324 |

The band the production endpoint was actually shipping covered **~47%** of outcomes against
a nominal 80% — roughly half. It was not a little narrow; it was wrong. Residual bands fit
strictly on prior folds land where they should (79.5%–88.2%), which confirms the harness is
measuring correctly and the KNN band itself is the problem. Rather than delete the number,
`/api/predict?method=aging_knn` now ships `meta.band_calibration` with the measured
coverage on every response and says so in the narration. Replacing it with per-horizon
residual bands is the open work.

Regenerate the report (needs a loaded database):

```bash
docker compose exec backend python -m app.toolkit.backtest_report
```

---

## Quick start

### Prerequisites

Docker Desktop. Python 3.11 on the host only if you want to run the ingestion pipeline or
the CSV loaders. Node 18+ only if you want to run the frontend outside Docker.

### 1. Bring up the stack

```bash
git clone https://github.com/cmartinez131/sabermetric-ai.git
cd sabermetric-ai
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for the LLM paths
docker compose up --build
```

- backend → <http://localhost:8000> (interactive docs at `/docs`)
- frontend → <http://localhost:3000>
- postgres → `localhost:5432`

```bash
curl -s http://localhost:8000/health    # {"status":"ok"}
```

Everything comes up without `.env` and without an API key — compose supplies working
defaults and the app falls back to rule-based parsing. You get an empty app, though, until
you load data.

### 2. Load the pitch-level data (host, ~3 hours unattended)

pybaseball is not yet compatible with the pandas 3.x the backend pins, so the pipeline gets
its own environment:

```bash
python3 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r data_pipeline/requirements.txt

export DATABASE_URL="postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db"

.venv-pipeline/bin/alembic upgrade head                                   # schema
.venv-pipeline/bin/python -m data_pipeline.ingest.cli backfill-all        # chadwick → statcast → bat-tracking → marts
```

Safe to interrupt and rerun — it resumes from the last completed chunk. Check progress any
time with `… ingest.cli status --source statcast_pitches`. To try it without the full
backfill, run one week: `… ingest.cli statcast --start 2024-06-03 --end 2024-06-09`.

### 3. Load the season-level batting data (host)

`batting_stats` comes from a CSV that is **not in the repo** (it is Savant's data, not
mine). Produce it from
[Baseball Savant → Statcast Custom Leaderboard](https://baseballsavant.mlb.com/leaderboard/custom):
seasons 2015–2025, player type *batter*, minimum 1 PA, all columns, "Download CSV" → save
as `data_pipeline/data/2015_2025_batters.csv`.

```bash
python3 -m venv venv && source venv/bin/activate
pip install pandas SQLAlchemy psycopg2-binary requests
export DATABASE_URL=postgresql://user:password@localhost:5432/baseball_db

python data_pipeline/scripts/load_batters.py            # CSV → batting_stats            (required)
python data_pipeline/scripts/fetch_player_profiles.py   # MLB StatsAPI → profiles/seasons (needs network)
python data_pipeline/scripts/build_player_features.py   # → player_features               (optional, see Limitations)
python data_pipeline/scripts/build_age_curves.py        # → league_age_curves             (optional, unread by the API)
# load_pitchers.py exists and needs its own CSV; nothing consumes pitching_stats yet
```

### First-run notes

- **macOS port 5432 shadowing.** If a local Postgres (Homebrew, Postgres.app) is already
  listening on loopback, it silently shadows the compose port mapping and the host loaders
  fail with `role "user" does not exist` — they are talking to *your* Postgres, not the
  container's. Either stop it (`brew services stop postgresql@14`) or point `DATABASE_URL`
  at a non-loopback interface (`$(ipconfig getifaddr en0)`), which Docker's wildcard
  listener answers.
- **The read-only role provisions itself.** Fresh volumes get it from
  `db/init/01-readonly-role.sh`; existing volumes get it at backend startup. No manual step.
- **Backtest report.** `/api/backtest/report` and the calibration numbers attached to KNN
  responses read `backend/app/ml_models/backtest_results.json`, which is committed. Regenerate
  it after loading your own data with `docker compose exec backend python -m app.toolkit.backtest_report`.
- **The LLM paths are optional.** Without `ANTHROPIC_API_KEY`, NL→SQL returns a default HR
  leaderboard and the classic agent uses rule-based parsing. Every `/api/*` structured
  endpoint works fully without a key.

---

## Demo

Each block below exercises a different layer. Outputs are trimmed real responses from a
loaded instance.

### The pipeline → mart → API path (bat tracking, 2024+)

```bash
curl -s -X POST http://localhost:8000/api/blast_leaderboard \
  -H "Content-Type: application/json" \
  -d '{"season":2025,"stat":"avg_bat_speed","limit":5,"min_swings":100}' | jq
```

```json
{"chart_type":"bar","series":[{"id":"avg_bat_speed","data":[
  {"x":"Giancarlo Stanton","y":80.61},{"x":"Oneil Cruz","y":78.76},
  {"x":"Junior Caminero","y":78.49},{"x":"Riley Adams","y":78.32},
  {"x":"Jordan Walker","y":78.07}]}],
 "meta":{"title":"Top 5 Avg Bat Speed (mph) — 2025 (min 100 competitive swings)",
         "qualifier":{"column":"competitive_swings","min":100}}}
```

A player's swing profile as percentiles against the qualified league (renders as a radar):

```bash
curl -s -X POST http://localhost:8000/api/bat_speed_profile \
  -H "Content-Type: application/json" \
  -d '{"player":"Aaron Judge","season":2025}' | jq
```

> Judge, 2025: bat speed **98th** percentile, fast-swing rate **98th**, blast rate **97th**,
> squared-up rate **40th**, contact **12th** — the shape of the trade-off, in one chart.
> `meta.qualified_pool: 579`.

League-wide bat speed vs production, binned by mph, with the Pearson correlation in `meta`:

```bash
curl -s -X POST http://localhost:8000/api/bat_speed_production \
  -H "Content-Type: application/json" \
  -d '{"season":2025,"production_stat":"woba","min_swings":100}' | jq '.meta'
```

```json
{"title":"wOBA by Avg Bat Speed — 2025","players":513,"pearson_r":0.226,"bin_width_mph":1.0}
```

Swinging harder correlates with more production, weakly (r = 0.23 across 513 qualified
hitters) — which is the honest answer, and the kind of thing this stack exists to check.

### The NL→SQL path (LLM drafts SQL, guard validates, read-only role executes)

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"fastest average bat speed in 2025, minimum 100 competitive swings"}' | jq
```

```json
{"chart_type":"bar","ai_source":"nl2sql",
 "narration":"Giancarlo Stanton posted the highest Avg Bat Speed (mph) for 2025 at 80.6.",
 "series":[{"id":"avg_bat_speed","data":[{"x":"Giancarlo Stanton","y":80.61}, …]}]}
```

One player against the league — the planner writes a `CASE` bucket and an `AVG`:

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"compare Aaron Judge blast rate to league average in 2025"}' | jq
```

```json
{"chart_type":"bar","ai_source":"nl2sql","series":[{"id":"blast_rate","data":[
  {"x":"Aaron Judge","y":0.1703},{"x":"League average","y":0.1073}]}]}
```

A filtered leaderboard that needs two stats and a league-relative threshold:

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"top 10 barrel rate in 2023 with above-average sprint speed, min 400 PA"}' | jq
```

```json
{"chart_type":"bar","ai_source":"nl2sql",
 "narration":"Shohei Ohtani posted the highest Barrel % for 2023 at 19.6.",
 "series":[{"id":"barrel_batted_rate","data":[
   {"x":"Shohei Ohtani","y":19.6},{"x":"Matt Chapman","y":17.1},{"x":"Jake Burger","y":16.7}, …]}]}
```

### The classic agent path (LLM picks a tool, toolkit computes)

Forecast wording (*project / predict / forecast / next season*) skips NL→SQL automatically
— the agent selects `marcel_project` and the toolkit does the arithmetic:

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"project Aaron Judge wOBA next season"}' | jq
```

```json
{"chart_type":"bar","ai_source":"agent","meta":{"method":"marcel"},
 "series":[{"id":"Projected woba","data":[{"x":"Next season","y":0.4334}]}],
 "narration":"Using the Marcel projection system, Aaron Judge is forecast to post a
              **wOBA of .433** in 2026 over an estimated **609.9 plate appearances**,
              well above the projected league average of .314."}
```

`?route=agent` forces this path for any prompt — useful for multi-player comparisons, which
the agent splits into one series per player (see Limitations for why NL→SQL does not):

```bash
curl -s -X POST "http://localhost:8000/api/prompt?route=agent" \
  -H "Content-Type: application/json" \
  -d '{"text":"compare Aaron Judge and Mookie Betts home runs from 2021 to 2024"}' | jq
```

```json
{"chart_type":"line","ai_source":"agent","series":[
  {"id":"Aaron Judge","data":[{"x":2021,"y":39},{"x":2022,"y":62},{"x":2023,"y":37},{"x":2024,"y":58}]},
  {"id":"Mookie Betts","data":[{"x":2021,"y":23},{"x":2022,"y":35},{"x":2023,"y":39},{"x":2024,"y":19}]}]}
```

### Structured endpoints (no LLM involved at all)

```bash
# Marcel projection (the default method)
curl -s -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"player_id":592450,"stat":"woba"}' | jq '.meta.marcel'

# Season-holdout comparison of forecast systems
curl -s -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"stat":"woba","start_year":2022,"end_year":2025,"mode":"compare"}' | jq '.narration'
# "Season-holdout backtest (2022–2025), RMSE by system for wOBA.
#  Best overall RMSE: Marcel (0.0336, n=1324)."

# Head-to-head, single season → bar; year range → line
curl -s -X POST http://localhost:8000/api/compare \
  -H "Content-Type: application/json" \
  -d '{"player_ids":[116338,120074],"stat":"home_run","year":2015}' | jq
```

### Watching the guard reject things

The guard needs no database, so you can drive it directly:

```bash
docker compose exec backend python -c "
from app.agent.sql_guard import guard_sql, SqlGuardError
for sql in [
    \"SELECT full_name, home_run FROM batting_stats WHERE year = 2024 ORDER BY home_run DESC LIMIT 10\",
    \"SELECT full_name FROM batting_stats LIMIT 1; SET statement_timeout='999s'\",
    \"SELECT * FROM secret_admin_table s JOIN player_profiles p ON p.player_id = s.player_id\",
    \"SEL/**/ECT * FROM batting_stats\",
    \"SELECT full_name FROM raw_statcast_pitches LIMIT 5\",
    \"SELECT pg_sleep(30) FROM batting_stats\",
]:
    try:
        print('PASS  ->', guard_sql(sql))
    except SqlGuardError as e:
        print('BLOCK ->', e)
"
```

```
PASS  -> SELECT full_name, home_run FROM batting_stats WHERE year = 2024 ORDER BY home_run DESC LIMIT 10;
BLOCK -> Multiple SQL statements are not allowed.
BLOCK -> Table not allowed: secret_admin_table
BLOCK -> Only single SELECT statements are allowed.
BLOCK -> Table not allowed: raw_statcast_pitches
BLOCK -> System catalogs and pg_* functions are not allowed.
```

---

## Tests and CI

```bash
# Backend + pipeline (no database required — 1 second)
python -m pytest tests/ -v

# Lint
ruff check backend tests data_pipeline db

# Frontend
cd frontend && npx eslint src --ext .js,.jsx --max-warnings=0 && CI=true npm test
```

| Suite | Tests | Covers |
|---|---|---|
| `tests/backend/test_sql_guard.py` | 69 | adversarial payloads, legitimate queries, lexer, LIMIT cap |
| `tests/backend/test_marcel.py` | 14 | weighting, ballast, age adjustment, rate vs counting stats |
| `tests/backend/test_backtest.py` | 12 | fold construction, leakage guards, coverage math |
| `tests/backend/test_battracking.py` | 10 | percentile profile, qualifier logic, binning |
| `tests/backend/test_aging_cutoff.py` | 5 | `max_year` leakage cutoff through every KNN query |
| `tests/pipeline/*` | 26 | chunk planning, watermark resume, upsert idempotency, quality gates, frame→rows |
| `frontend/src/utils/*.test.js` | 11 | CSV export, stat labels |

**136 backend/pipeline tests + 11 frontend tests, all passing; ruff and eslint clean.**
`.github/workflows/ci.yml` runs exactly those commands on every push and PR.
`scripts/run_tests.sh` is a separate integration smoke test that needs the stack up and
data loaded.

---

## Configuration

Everything has a working default; `.env` is optional. See `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://user:password@db:5432/baseball_db` | Compose network form. Host-side loaders need the `localhost`/`127.0.0.1` form. |
| `ANTHROPIC_API_KEY` | *(none)* | Optional. Without it, both LLM paths degrade to rule-based fallbacks. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | |
| `NL2SQL_RO_USER` / `NL2SQL_RO_PASSWORD` | `nl2sql_ro` / `nl2sql_ro` | The SELECT-only role NL→SQL executes as. **Change the password for any real deployment.** |
| `READONLY_DATABASE_URL` | *(derived)* | Full override if the read-only role lives elsewhere. |
| `CORS_ALLOW_ORIGINS` | *(unset → `*`)* | Comma-separated. Set it in production; with `*`, credentials are disabled. |
| `REACT_APP_API_URL` | `http://localhost:8000` | Frontend → backend base URL (CRA). |

`.env` is gitignored, `.env.example` holds placeholders only, and a full-history scan for
credential patterns comes back empty.

---

## Limitations

Written down because they are true, not because they are flattering.

**The KNN aging bands are overconfident.** Measured coverage 48.7% (HR) and 47.1% (wOBA)
against a nominal 80% — see the calibration table above. The method is labeled
`"status": "experimental"` in `meta.band_calibration` on every response and the narration
says the band is a lower bound on uncertainty. It should be replaced by per-horizon
residual bands; that work is not done.

**NL→SQL mis-shapes two-player year-range prompts.** For a prompt naming *two* players over
a *range* of seasons, the planner correctly emits `SELECT year, name, stat …`, but the
shaping layer groups only on the x-axis column, so both players collapse into a single
series and the narration labels the peak by **year** instead of by player — *"2022 posted
the highest HR for 2021–2024 at 62.0."* The numbers are right; the framing is wrong. The
fallback in `api/prompt.py` only triggers on an empty payload or a non-line chart type, and
this response is a non-empty line chart, so it slips through. Workaround today:
`?route=agent`, which returns correctly split per-player series. Fix: group on the name
column when the projection has both a time axis and an entity column.

**Bat-tracking data is 2024+ and there are only two seasons of it.** 650 player-seasons in
2024, 671 in 2025. Any "trend" in bat speed is a two-point line, and no aging or
year-over-year claim about swing metrics should be taken seriously yet. Two different
`avg_bat_speed` numbers also exist on purpose: Savant's leaderboard
(`mart_bat_tracking_season`) averages **competitive swings**, while the pitch-derived mart
(`mart_batter_pitch_season`) averages **all measured swings**, so the pitch-derived value
reads slightly lower. Both are kept and documented rather than reconciled into a single
misleading number.

**Entity resolution is substring matching, and it is ambiguous.** Players are resolved with
`full_name ILIKE '%fragment%'`. Three names in `batting_stats` currently map to two distinct
`player_id`s each — Max Muncy, Carlos Pérez, Daniel Robertson — and a prompt naming one of
them silently blends both careers. Nicknames, accents, and Jr./Sr. suffixes are not
normalized, and there is no disambiguation prompt. The Chadwick crosswalk is loaded and
would support proper ID-based resolution; it is not wired into the name resolver yet.

**`player_features` is optional and can be absent.** It is built by
`build_player_features.py`, not by the ingestion pipeline. If you skip that step the table
does not exist; the planner then sees an empty column list for it while one few-shot example
still references `f.woba_3yr`, so a prompt that leans on rolling features can produce SQL
that fails and silently falls back. The guard allowlists the table either way.

**2020 is used at face value.** The 60-game COVID season participates in trailing windows
and Marcel weights with no adjustment.

**"League average" means the Savant export population.** League rates are computed from the
players present in the batting CSV (roughly the 50+ PA population), not from all MLB
hitters. Experience buckets in the backtest are also left-truncated: the panel starts in
2015, so a ten-year veteran in 2022 counts at most 7 prior seasons.

**Schema drift is logged, not absorbed.** The `raw_statcast_pitches` manifest is frozen in
migration `0001`. New upstream columns are logged as drift and dropped until someone writes
a migration. That is deliberate — silent widening is worse — but it does mean the pipeline
needs maintenance when Savant adds fields.

**Half-built and unread surfaces.** `pitching_stats` loads (8,264 rows) and nothing consumes
it; it is not in the guard's allowlist. `league_age_curves` is built by a script but
`toolkit/aging.py` recomputes curves inline. The `Pricing` page is a routed mock advertising
features that do not exist and is intentionally unlinked from the nav.

**Deployment posture is development-grade.** Compose mounts source and runs
`uvicorn --reload`; CORS defaults to `*`; `/api/history/*` "ownership" is a client-supplied
`X-Session-Id` header, which is a scoping mechanism and not authentication; and there is no
rate limiting in front of the LLM paths. Not a public multi-tenant deployment as-is.

**Frontend is still Create React App.** `react-scripts` is effectively unmaintained. The
Vite migration was the first thing cut when the pipeline work ran long.

---

## Data sources and attribution

This project reads public baseball data. It is a personal, non-commercial engineering
portfolio project and is not affiliated with, endorsed by, or sponsored by MLB Advanced
Media, any MLB club, or any data provider below.

- **Baseball Savant / MLB Advanced Media** — Statcast pitch-level data, the bat-tracking
  leaderboard, and the custom-leaderboard batting export, retrieved from
  [baseballsavant.mlb.com](https://baseballsavant.mlb.com). Statcast data is © MLB Advanced
  Media, L.P., made available for non-commercial use under MLB's terms; see the
  [MLB Terms of Use](http://gdx.mlb.com/components/copyright.txt). The batting CSV is
  deliberately **not** redistributed in this repo — you generate your own.
- **MLB Stats API** — player biographical and season metadata via
  `statsapi.mlb.com`, subject to the same MLB copyright notice.
- **[pybaseball](https://github.com/jldbc/pybaseball)** (MIT) — the Statcast and Chadwick
  fetchers. The bat-tracking leaderboard is fetched from Savant's CSV endpoint directly
  because the released pybaseball (2.2.7) does not expose it yet.
- **[Chadwick Baseball Bureau Register](https://github.com/chadwickbureau/register)** —
  the MLBAM ↔ FanGraphs ↔ Baseball-Reference ↔ Retrosheet ID crosswalk, licensed
  **CC BY-SA 4.0**. The `raw_chadwick_people` table is derived from it and therefore carries
  the same ShareAlike obligation.
- **Retrosheet** — the Chadwick register includes Retrosheet person IDs (`key_retro`,
  present on 24,366 of 24,818 ingested rows). No Retrosheet event, game, or schedule files
  are used. Per Retrosheet's request:

  > The information used here was obtained free of charge from and is copyrighted by
  > Retrosheet. Interested parties may contact Retrosheet at
  > [www.retrosheet.org](https://www.retrosheet.org).

Baseball terminology and the Marcel projection method are due to Tom Tango; the
implementation here is my own.

---

## Repo layout

```
sabermetric-ai/
├── backend/app/
│   ├── api/          analytics · prompt · history · backtest · schemas (Pydantic contract)
│   ├── agent/        nl2sql · sql_guard · classic tool-picker · shared common.py
│   ├── toolkit/      stats · marcel · aging · projections · battracking · backtest · ml
│   └── db/           engines (RW + read-only role) · ORM models
├── data_pipeline/
│   ├── ingest/       runner · chunks · watermarks · upsert · quality · sources · marts
│   └── scripts/      CSV + StatsAPI loaders (season-level data)
├── db/
│   ├── init/         first-boot read-only role provisioning
│   └── migrations/   Alembic
├── frontend/src/     ChartRenderer · pages · hooks/api.js · utils
├── tests/
│   ├── backend/      sql_guard (69) · marcel · backtest · battracking · aging cutoff
│   └── pipeline/     chunking · watermarks · upserts · quality gates
├── docs/BACKTEST.md  measured forecast accuracy + calibration
└── docker-compose.yml
```

---

## License

No license granted yet — all rights reserved pending a decision. Third-party data retains
its own terms; see [attribution](#data-sources-and-attribution) above. If you want to reuse
any of this, open an issue and ask.
