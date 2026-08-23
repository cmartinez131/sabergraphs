# SaberGraphs

Ask baseball questions in plain English, get charts back.

```
"compare Volpe and Judge home runs in their rookie seasons"
"lowest ERA in 2024, minimum 150 innings"
"fastest average bat speed in 2025, minimum 100 competitive swings"
```

The AI never generates a number. It figures out which players and stats you
mean (and asks you to pick when a name is ambiguous, like the two Max
Muncys), then either writes one SQL query that a safety layer validates
before a read-only database role runs it, or calls built-in analytics like
projections and rookie-season comparisons. Every value on every chart comes
out of PostgreSQL.

Built with Python, FastAPI, SQLAlchemy, PostgreSQL, React, Nivo, Docker,
pandas, scikit-learn, and the Claude API.

## How it works

```mermaid
flowchart LR
    Q["You ask a question"] --> PRE["Resolve players + stats\n(asks if unclear)"]
    PRE --> PLAN{"Pick the tool"}
    PLAN -- "writes one SELECT" --> GUARD["SQL guard\n+ read-only role"]
    PLAN -- "built-in analytics" --> TOOL["Projections,\nrookie alignment"]
    GUARD --> DB[("PostgreSQL")]
    TOOL --> DB
    DB --> CHART["Chart + summary"]
```

Some things worth knowing about the internals:

- Every query passes a SQL safety layer (single SELECT only,
  table allowlist, comment and quoting tricks rejected, hard row limit) and
  runs as a SELECT-only Postgres role with a 5 second timeout. That layer
  has a 69-test suite of SQL injection payloads.
- Player names match on exact tokens, never substrings, so "lombard" can
  never silently match Lombardozzi. Unknown names fall back to the MLB
  Stats API for identity only, which is how the app can say "no data for
  George Lombard Jr. (MLB debut 2026-08-04)" instead of guessing.
- Rookie seasons are computed in SQL with window functions over career
  at-bats, so Judge's rookie year resolves to 2017 (52 HR), not his 4-HR
  2016 cup of coffee.
- Projections use Marcel, and a season-holdout backtest showed it beating
  the fancier KNN-aging model I built first (wOBA RMSE 0.0336 vs 0.0499),
  so the simple model is the default. The KNN uncertainty bands measured
  ~47% coverage against a nominal 80%, so they ship labeled experimental.
  Full numbers in [docs/BACKTEST.md](docs/BACKTEST.md).
- The pitch data lands through a resumable, idempotent pipeline (3.8M
  Statcast pitches, per-chunk quality checks, watermark-based crash
  recovery).

## The data

| | Coverage |
|---|---|
| Batting stats (7,375 player-seasons) | 2015 to 2025 |
| Pitching stats (8,264 player-seasons) | 2015 to 2025 |
| Statcast bat tracking | 2024 to 2025 (tracking began in 2024) |
| Raw Statcast pitches (3.8M) | 2021 to 2025 |

## Run it locally

Needs Docker. Python 3.11 on the host only for loading data.

```bash
git clone https://github.com/cmartinez131/sabergraphs.git
cd sabergraphs
docker compose up --build
# backend http://localhost:8000 (API docs at /docs), frontend http://localhost:3000
```

It boots with no config and no API key (rule-based fallbacks), but starts
empty. To load data:

```bash
# pitch-level pipeline (own venv; pybaseball needs an older pandas)
python3 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r data_pipeline/requirements.txt
export DATABASE_URL="postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db"
.venv-pipeline/bin/alembic upgrade head
.venv-pipeline/bin/python -m data_pipeline.ingest.cli backfill-all   # ~3h, resumable

# season-level batting/pitching CSVs (Baseball Savant custom leaderboard
# exports, 2015-2025, saved into data_pipeline/data/)
python data_pipeline/scripts/load_batters.py
python data_pipeline/scripts/load_pitchers.py
python data_pipeline/scripts/fetch_player_profiles.py
```

macOS note: a local Postgres on port 5432 shadows the Docker one. Stop it,
or point DATABASE_URL at your en0 IP instead of 127.0.0.1.

Try it:

```bash
curl -s -X POST http://localhost:8000/api/prompt \
  -H "Content-Type: application/json" \
  -d '{"text":"compare volpe and judge home runs in their rookie seasons"}'
```

## Tests

```bash
python -m pytest tests/ -v    # 186 tests, no database needed
cd frontend && CI=true npm test
```

CI runs pytest, ruff, eslint, and the frontend tests on every push.

## Data sources

Personal, non-commercial project. Not affiliated with MLB.

- Baseball Savant / MLB Advanced Media: Statcast data and season exports
  ([MLB terms](http://gdx.mlb.com/components/copyright.txt)). 
- MLB Stats API: player identity and profiles.
- [pybaseball](https://github.com/jldbc/pybaseball) (MIT).
- [Chadwick Bureau Register](https://github.com/chadwickbureau/register)
  (CC BY-SA 4.0) for the player ID references. It includes Retrosheet IDs