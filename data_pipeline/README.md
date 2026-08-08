# data_pipeline — pitch-level ingestion

A resumable, idempotent ETL system that lands Baseball Savant pitch-level data,
bat-tracking leaderboards, and the Chadwick ID crosswalk into Postgres, layered
raw → staging → mart.

```mermaid
flowchart LR
    subgraph sources [Sources]
        SC["statcast()<br/>pitch level, weekly chunks"]
        BT["Savant bat-tracking<br/>leaderboard CSV, per season"]
        CH["Chadwick register<br/>ID crosswalk"]
    end
    subgraph raw [RAW — landed as-is]
        RSP[raw_statcast_pitches<br/>PK game_pk, at_bat_number, pitch_number]
        RBT[raw_bat_tracking<br/>PK season, batter_mlbam]
        RCP[raw_chadwick_people<br/>PK key_mlbam]
    end
    subgraph stg [STAGING — typed views]
        SP[stg_pitches<br/>regular season only]
        SB[stg_bat_tracking]
        SPL[stg_players]
    end
    subgraph mart [MART — API reads]
        M1[mart_batter_pitch_season]
        M2[mart_bat_tracking_season]
    end
    WM[(ingest_watermarks)]
    SC --> RSP --> SP --> M1
    BT --> RBT --> SB --> M2
    CH --> RCP --> SPL --> M1
    SPL --> M2
    SC -.progress.-> WM
    BT -.progress.-> WM
    CH -.progress.-> WM
```

## Environment

The pipeline runs on the **host** (not in compose) and has its own environment —
pybaseball is not yet compatible with the pandas 3.x the backend pins:

```bash
python3 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r data_pipeline/requirements.txt
```

Connection: `DATABASE_URL`, host-side form. Default when unset:
`postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db`.

> **Port 5432 clash**: if a local (e.g. Homebrew) Postgres also listens on
> loopback, it shadows the compose port mapping and you'll see
> `role "user" does not exist`. Either stop the local Postgres
> (`brew services stop postgresql@14`) or point `DATABASE_URL` at a
> non-loopback interface (e.g. `$(ipconfig getifaddr en0)`), which Docker's
> wildcard listener answers.

## Load order

```bash
export DATABASE_URL="postgresql+psycopg2://user:password@127.0.0.1:5432/baseball_db"

# 1. schema (Alembic; idempotent)
.venv-pipeline/bin/alembic upgrade head

# 2. everything, in order (chadwick → statcast → bat-tracking → marts):
.venv-pipeline/bin/python -m data_pipeline.ingest.cli backfill-all

# or step by step:
.venv-pipeline/bin/python -m data_pipeline.ingest.cli chadwick
.venv-pipeline/bin/python -m data_pipeline.ingest.cli statcast            # config seasons
.venv-pipeline/bin/python -m data_pipeline.ingest.cli statcast --start 2024-06-03 --end 2024-06-16
.venv-pipeline/bin/python -m data_pipeline.ingest.cli bat-tracking
.venv-pipeline/bin/python -m data_pipeline.ingest.cli marts
.venv-pipeline/bin/python -m data_pipeline.ingest.cli status --source statcast_pitches
```

Seasons, chunk size, polite delays and quality thresholds live in
`data_pipeline/config.toml` (default seasons 2021–2025, weekly chunks,
Feb 20 – Nov 10 per season ⇒ ~38 chunks/season, ~190 total, roughly 2.5–3.5
hours for the full backfill).

The legacy CSV loaders (`scripts/load_batters.py` etc.) are unchanged and
independent; see the repo-root README for that flow.

## Engineering properties

- **Idempotent upserts** — every load is `INSERT … ON CONFLICT (natural key)
  DO UPDATE`. Reruns and overlapping windows can never duplicate rows.
- **Resumable backfill** — `ingest_watermarks` records one row per chunk.
  A chunk is claimed `in_progress` before fetching; rows and the `completed`
  marker are committed in the **same transaction**, so a crash (`kill -9`
  included) leaves either nothing or a fully-marked chunk. Reruns skip
  `completed` chunks and redo everything else. A failed chunk doesn't abort
  the run — it's logged, reported at exit (nonzero), and retried on rerun.
- **Data-quality gates** (per chunk, fail loudly): natural-key columns must
  be 100 % non-null; in-frame duplicate keys are dropped (keeping last) and
  hard-fail above 0.5 %; drift columns (fetched but not in the manifest) are
  logged, never silently dropped.
- **Frozen schema manifest** — `raw_statcast_pitches` columns are pinned in
  `ingest/models.py` and migration `0001` (derived from a live fetch,
  deprecated columns excluded). New upstream columns → new migration.
- **Migrations** — Alembic (`alembic.ini` at repo root, `db/migrations/`).
  Runs as the compose `user` role, and the read-only role's
  `ALTER DEFAULT PRIVILEGES` grant means new tables are automatically
  SELECT-able by the NL→SQL role.

## Metric notes

- `mart_batter_pitch_season` aggregates **regular-season** pitches
  (`stg_pitches` filters `game_type = 'R'`). Swing/whiff/chase/contact use the
  standard Savant description sets; barrel = `launch_speed_angle = 6`;
  hard-hit = EV ≥ 95; fast swing = bat speed ≥ 75 mph.
- `avg_bat_speed` here averages **all measured swings**, while Savant's
  leaderboard (→ `mart_bat_tracking_season`) uses **competitive swings** only,
  so the pitch-derived number reads slightly lower. Both are kept — that's a
  feature, not drift.
- Bat-tracking fields (`bat_speed`, `swing_length`) exist from **2024** on;
  earlier seasons land NULL.
- The bat-tracking leaderboard is fetched from Savant's CSV endpoint directly
  because the released pybaseball (2.2.7) doesn't expose it yet.
