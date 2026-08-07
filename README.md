# Sabermetric AI

**Natural-language baseball analytics → charts & projections.**
Type a question, get a Nivo chart back:

```
Frontend → POST /api/prompt → Agent → Toolkit / SQL guard → Postgres → canonical payload → Nivo chart
                                 ↓
               Two paths: NL→SQL (LLM writes one guarded SELECT)
                       or Classic (LLM picks a toolkit function)
```

---

## ✨ What this does (today)

* Turn prompts like "compare David Ortiz vs Torii Hunter HR in 2015" into a **bar chart**.
* "Project Ortiz wOBA next season" → simple **projection** from trailing seasons.
* Leaderboards, career arcs, rolling means, histograms, percentiles, improvement deltas.
* **Canonical chart payload**: `{ chart_type, series, narration, meta, ai_source }` that the frontend renders with Nivo.
* Optional Claude agent to parse free text via two paths — NL→SQL or classic tool-picker; **no LLM required** (rule-based fallback included).

> Active WIP. The "what-if" scenario engine + richer projections are on the roadmap (Phase 3).

---

## 🧱 Tech stack

* **Backend**: FastAPI, SQLAlchemy
* **Frontend**: React (Create React App) + Nivo
* **DB**: PostgreSQL
* **AI (optional)**: Anthropic Claude (`claude-sonnet-4-6` by default); rules-based fallback without a key
* **DevOps**: Docker & Docker Compose
* **Data**: wide CSVs (2015–2025 batting stats) + MLB StatsAPI profiles → Postgres

---

## 📁 Repo layout

```
/sabermetric-ai
|-- backend/
|   |-- app/
|   |   |-- api/          # FastAPI endpoints (analytics, prompt, history, backtest)
|   |   |-- agent/        # Claude planners (nl2sql + classic tool-picker) + sql_guard
|   |   |-- db/           # SQLAlchemy models, sessions, read-only role provisioning
|   |   |-- toolkit/      # analytics + projections (data truth)
|   |   |-- main.py       # FastAPI entrypoint
|   |-- Dockerfile
|   |-- requirements.txt
|
|-- data_pipeline/
|   |-- scripts/          # host-side loaders (see "Load the data" below)
|   |-- data/             # CSVs live here (gitignored; obtain separately)
|
|-- db/init/              # docker-entrypoint SQL role provisioning
|-- frontend/             # React app (Nivo charts)
|-- tests/backend/        # pytest (sql_guard adversarial suite)
|-- notebooks/            # DS exploration + model protos
|-- docker-compose.yml
```

---

## 🚀 Quick start

### 0) Prereqs

* Docker Desktop
* Python 3.10+ (for the host-side loaders)
* Node 18+ (only if you run the frontend outside Docker)

### 1) Configure environment

```bash
cp .env.example .env    # then add your ANTHROPIC_API_KEY (optional)
```

### 2) Bring everything up

```bash
docker compose up --build
# backend:  http://localhost:8000
# frontend: http://localhost:3000
# postgres: localhost:5432 (compose service name: db)
```

### 3) Load the data (run on your host, not in a container)

The batting CSV (`2015_2025_batters.csv`) is **not** checked into the repo —
place it in `data_pipeline/data/` first. Loaders read `DATABASE_URL` from the
environment and need the **localhost** form:

```bash
python3 -m venv venv && source venv/bin/activate
pip install pandas SQLAlchemy psycopg2-binary requests

export DATABASE_URL=postgresql://user:password@localhost:5432/baseball_db

python data_pipeline/scripts/load_batters.py            # batting CSV → batting_stats
python data_pipeline/scripts/fetch_player_profiles.py   # MLB StatsAPI → player_profiles, player_seasons
python data_pipeline/scripts/build_player_features.py   # derived features → player_features
python data_pipeline/scripts/build_age_curves.py        # league aging curves
# optional: load_pitchers.py (needs 2015_2025_pitchers.csv; nothing reads it yet)
```

### 4) Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## 🔒 NL→SQL safety design

The LLM writes SQL, but it is never trusted:

* **`backend/app/agent/sql_guard.py`** validates every candidate statement:
  single statement only, leading keyword must be `SELECT` (allowlist, not a
  denylist), comments stripped with Postgres semantics, string literals
  masked before keyword checks, quoting/escaping obfuscation rejected,
  every `FROM`/`JOIN` table checked against a four-table whitelist,
  `information_schema`/`pg_*` blocked, and a hard `LIMIT 200` cap.
* **Read-only execution**: guarded SQL runs as the `nl2sql_ro` Postgres role —
  SELECT-only grants, `statement_timeout = 5s`, `default_transaction_read_only`.
  The role is provisioned by `db/init/01-readonly-role.sh` on fresh volumes and
  idempotently at backend startup.
* **Adversarial test suite**: `tests/backend/test_sql_guard.py` — 55 tests
  covering multi-statement injection, comment-hidden keywords, `COPY … TO
  PROGRAM`, `pg_sleep` DoS, UNION/CTE smuggling, quoting tricks, and the
  legitimate query shapes that must keep working.

```bash
pip install pytest && python -m pytest tests/backend/ -v
```

---

## 🧪 Try some API calls

> Canonical response shape:
>
> ```json
> {
>   "chart_type": "bar" | "line" | "radar" | "histogram",
>   "series": [...],
>   "narration": "human-friendly summary",
>   "meta": { "title": "..." },
>   "ai_source": "nl2sql" | "sql_fallback" | "agent"
> }
> ```

### Compare (single season → bar)

```bash
curl -s -X POST http://localhost:8000/api/compare \
  -H "Content-Type: application/json" \
  -d '{"player_ids":[116338,120074], "stat":"home_run", "year":2015}' | jq
# 116338 = Torii Hunter, 120074 = David Ortiz
```

### Compare (range → line)

```bash
curl -s -X POST http://localhost:8000/api/compare \
  -H "Content-Type: application/json" \
  -d '{"player_ids":[116338,120074], "stat":"home_run", "start_year":2015, "end_year":2018}' | jq
```

### Predict

```bash
curl -s -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"player_id":120074,"stat":"woba","years":3}' | jq
```

### Leaderboard

```bash
curl -s -X POST http://localhost:8000/api/leaderboard \
  -H "Content-Type: application/json" \
  -d '{"stat":"home_run","year":2015,"limit":10}' | jq
```

### Prompt (free text → NL→SQL or agent)

```bash
curl -s -X POST "http://localhost:8000/api/prompt" \
  -H "Content-Type: application/json" \
  -d '{"text":"Top 10 home run hitters in 2024"}' | jq
```

### Backtest (rolling-origin forecast evaluation)

```bash
curl -s -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"stat":"woba","start_year":2018,"end_year":2024,"lookback":3,"method":"baseline"}' | jq
```

---

## 📊 Data model (current)

* **`batting_stats`** — all CSV columns; ORM composite key `(player_id, year)`;
  common columns explicitly mapped, the rest accessed via reflection.
* **`player_profiles` / `player_seasons`** — bio + season metadata from MLB StatsAPI.
* **`player_features`** — derived rolling features (e.g. `woba_3yr`).
* **`league_age_curves`** — output of `build_age_curves.py` (currently unused
  by the API; `toolkit/aging.py` recomputes curves inline).
* **`pitching_stats`** — loadable via `load_pitchers.py`; no consumer yet.

**Tip:** stat names in API calls are snake_case CSV headers (`home_run`,
`woba`, `sprint_speed`). "Unknown/unsupported stat" means the spelling
doesn't match a column.

---

## ⚙️ Config & environment

See `.env.example` for the full annotated list.

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://user:password@db:5432/baseball_db` | Containers use host `db`; host-side loaders use `localhost` |
| `ANTHROPIC_API_KEY` | (none) | Optional — rule-based fallback without it |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | |
| `NL2SQL_RO_PASSWORD` | `nl2sql_ro` | Password for the read-only NL→SQL role |
| `REACT_APP_API_URL` | `http://localhost:8000` | Frontend → backend base URL (CRA) |

---

## 🧰 Developer workflow

* **Run everything**: `docker compose up --build`
* **Load data**: see "Load the data" above (host-side, `localhost` URL)
* **Unit tests**: `python -m pytest tests/backend/ -v`
* **Smoke tests**: `scripts/run_tests.sh` (needs the stack up + data loaded)
* **Frontend dev**: `cd frontend && npm start` / `npm test` / `npm run build`

---

## 🧭 Roadmap

* ✅ Phase 1 — data load, core endpoints, agent + fallback
* ✅ Phase 2 — React frontend, Nivo charts, multiple chart types
* 🔜 Phase 3 — "what-if" scenario engine, Monte-Carlo uncertainty bands
* Beyond — automated pipelines (Statcast), pitcher models, comps engine

---

## 🧠 Design notes

* **Data is truth.** The toolkit queries Postgres and shapes Nivo series. The
  agent chooses tools and parameters; it does **not** invent numbers.
* **Backend decides `chart_type`.** The frontend renders whatever comes back.
* **Canonical payload** keeps the frontend dead simple & portable.
* **Reflection fallback** lets the CSV grow columns without exploding the ORM.
* **LLM SQL is sandboxed** — see "NL→SQL safety design" above.

---

## 🧾 License

Personal/experimental. Decide license before public release.

---

## Appendix: Handy test IDs & stats

* **Players**: Torii Hunter `116338`, David Ortiz `120074`
* **Stats** (snake_case): `home_run`, `woba`, `batting_avg`,
  `barrel_batted_rate`, `sprint_speed`, `plate_appearances`, `k_percent`,
  `slg_percent`, `on_base_percent` …and most CSV headers.
