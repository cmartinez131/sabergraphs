# Sabermetric AI

**Natural-language baseball analytics → charts & projections.**
Type a question, get a Nivo chart back. The stack is simple & robust:

```
Frontend → Backend (endpoint) → Toolkit → DB
           ↑                          ↓
        Agent (LLM) ←— optional —→  Toolkit shapes series → Backend returns canonical payload → Frontend renders Nivo
```

---

## ✨ What this does (today)

* Turn prompts like “compare David Ortiz vs Torii Hunter HR in 2015” into a **bar chart**.
* “Project Ortiz wOBA next season” → simple **projection** from trailing seasons.
* Leaderboards, career arcs, rolling means, histograms, percentiles, improvement deltas.
* **Canonical chart payload**: `{ chart_type, series, narration }` that the frontend renders with Nivo.
* Optional LLM agent to parse free-text; **no LLM required** (there’s a lightweight fallback).

> You’re reading an active WIP. The “what-if” scenario engine + richer projections land in Phase 3 (see roadmap).

---

## 🧱 Tech stack

* **Backend**: FastAPI, SQLAlchemy
* **Frontend**: React + Nivo
* **DB**: PostgreSQL
* **AI (optional)**: OpenAI (you can ship with the rules-based fallback)
* **DevOps**: Docker & Docker Compose
* **Data**: A wide CSV (2015-2024 batting stats) → Postgres

---

## 📁 Repo layout

```
/sabermetric-ai
|-- backend/
|   |-- app/
|   |   |-- api/          # FastAPI endpoints (analytics + prompt)
|   |   |-- agent/        # LLM planner (optional); rule fallback built in
|   |   |-- core/         # config
|   |   |-- db/           # SQLAlchemy models & session
|   |   |-- ml_models/    # saved models (future)
|   |   |-- simulation/   # what-if engine (future)
|   |   |-- toolkit/      # analytics + projections (data truth)
|   |   |-- main.py       # FastAPI entrypoint
|   |-- Dockerfile
|   |-- requirements.txt
|
|-- data_pipeline/
|   |-- scripts/
|   |   |-- load_csv.py   # host-side loader: CSV → Postgres
|   |-- data/
|       |-- 2015_2024_batting_stats.csv
|
|-- frontend/
|   |-- src/              # React app (Nivo charts)
|   |-- Dockerfile
|
|-- notebooks/            # DS exploration + model protos
|-- docker-compose.yml
|-- README.md
```

---

## 🚀 Quick start

### 0) Prereqs

* Docker Desktop
* Python 3.10+ (for the host-side CSV loader)
* Node 18+ (only if you run the frontend outside Docker)

### 1) Bring everything up

```bash
docker compose up --build
# backend: http://localhost:8000
# frontend: http://localhost:3000
# postgres: localhost:5432 (container name: db)
```

### 2) Load the sample CSV into Postgres (run on your host, not in a container)

> Make sure the DB container is running first: `docker compose up -d db`

```bash
python3 -m venv venv
source venv/bin/activate
pip install pandas SQLAlchemy psycopg2-binary

python data_pipeline/scripts/load_csv.py
# connects to postgresql://user:password@localhost:5432/baseball_db
# reads data_pipeline/data/2015_2024_batting_stats.csv
# creates/replaces table `batting_stats` with all CSV columns
```

### 3) Hit a health check

```bash
curl http://localhost:8000/
# {"message":"Hello from Sabermetric AI"}
```

---

## 🧪 Try some API calls

> The canonical response you’ll see looks like:
>
> ```json
> {
>   "chart_type": "bar" | "line" | "radar" | "histogram",
>   "series": [...],
>   "narration": "human-friendly summary"
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

### Predict (single season → bar)

```bash
curl -s -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"player_id":120074,"stat":"woba","years":3}' | jq
```

### Predict (multi-year → line)

```bash
curl -s -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"player_id":120074,"stat":"woba","years":3,"horizon":5}' | jq
```

### Leaderboard

```bash
curl -s -X POST http://localhost:8000/api/leaderboard \
  -H "Content-Type: application/json" \
  -d '{"stat":"home_run","year":2015,"limit":10}' | jq
```

### Prompt (free text → agent → toolkit)

> If you set `OPENAI_API_KEY`, the agent uses an LLM; otherwise it falls back to simple rules.

```bash
curl -s -X POST "http://localhost:8000/api/prompt?debug=1" \
  -H "Content-Type: application/json" \
  -d '{"text":"Compare David Ortiz vs Torii Hunter HR in 2015"}' | jq
```

---

## 🖥️ Frontend

* Dev server (via Docker): `http://localhost:3000`
* Type in a query (e.g., “Compare Ortiz vs Hunter HR in 2015”) and hit **Ask AI**.
* The frontend dynamically renders the chart returned by the backend’s canonical payload.

> **Note**: By design the **backend decides chart type** (bar vs line vs radar), and the **frontend just renders**. The plan is to allow **user-selectable viz options** (color, stacked/grouped, smooth line, labels) via a small whitelisted `viz` spec later.

---

## 📊 Data model (current)

* **Table**: `batting_stats`
* **Composite key** in ORM: `(player_id, year)`
* **Columns**: all columns from the CSV are loaded into the Postgres table. The ORM explicitly defines the common ones the toolkit uses frequently (e.g., `full_name`, `player_age`, `home_run`, `batting_avg`, `woba`, `barrel_batted_rate`, `sprint_speed`, `plate_appearances`).
* The toolkit accesses **any other CSV column** safely by name (snake_case) via SQLAlchemy reflection.

**Tip:** The stat names you send in the API must match CSV column names in **snake_case** (e.g., `home_run`, `woba`, `sprint_speed`). If a request fails with “Unknown/unsupported stat”, check your spelling/format.

---

## ⚙️ Config & environment

Backend reads these (via Docker env or shell):

* `DATABASE_URL` – inside containers it’s like `postgresql+psycopg2://postgres:postgres@db:5432/postgres`
  Host-side loader uses `postgresql://user:password@localhost:5432/baseball_db`.
* `OPENAI_API_KEY` – optional. If absent, the agent uses a rule-based fallback.
* `OPENAI_MODEL` – optional. Defaults to `gpt-4o-mini`.
* Frontend uses `VITE_API_URL` (optional). Defaults to `http://localhost:8000`.

---

## 🧰 Developer workflow

* **Run everything**: `docker compose up --build`
* **Load data**: `python data_pipeline/scripts/load_csv.py` (from host, one-time or whenever you replace the CSV)
* **Hit endpoints**: see curl examples above or use the frontend.
* **Tests** (smoke): `scripts/run_tests.sh`

---

## 🔍 Troubleshooting

* **500 on `/api/predict`**
  Usually a bad `stat` name or missing data for that player. Try `woba` or `home_run`. Ensure the CSV was loaded successfully.
* **“Unknown/unsupported stat”**
  The toolkit validates stat names (snake_case). Check the exact CSV column header.
  Example: `plate_appearances` not `pa` (unless you aliased it on load).
* **Frontend shows no chart**
  Open dev tools → Network → check `chart_type` and `series` in the JSON. If empty, your query likely returned no matching rows. Try a known combo from the sample data.
* **Connection reset while booting**
  The compose script waits for backend health—give it a few seconds after you see the containers up.
* **Host vs Container DB URLs**

  * Host scripts connect to `localhost:5432`.
  * Backend container connects to the `db` hostname inside the compose network.

---

## 🧭 Roadmap (12-week plan)

**Phase 1 – Foundation (Weeks 1–4)**

* ✅ Data load from CSV into Postgres
* ✅ Core FastAPI endpoints + Toolkit (compare/leaderboard/etc.)
* ✅ Optional LLM agent + fallback

**Phase 2 – Frontend & Feature Expansion (Weeks 5–8)**

* ✅ React app + dynamic chart renderer (Nivo)
* ✅ Multiple chart types (bar/line/radar/hist) via canonical payload
* ➡️ UX polish, error states, narration

**Phase 3 – “What-If” Engine (Weeks 9–12)**

* Projection model (glass-box features)
* Scenario deltas (e.g., +5% plate discipline)
* Guardrails + uncertainty (MC bands)
* Baseline vs Scenario comparison views

**Beyond**

* Automated data pipelines (Statcast, live feeds), pitcher models, team-level analysis, comps engine, user accounts, saved dashboards, freemium/paywall.

---

## 🧠 Design notes

* **Data is truth.** The toolkit queries Postgres and shapes Nivo series. The agent can *choose the tool* and *pass parameters*, but it does **not** invent numbers.
* **Canonical payload** keeps frontend dead simple & portable.
* **Reflection fallback** lets you add lots of CSV columns without exploding the ORM class.
* **Security/robustness**: stat names are validated (`^[a-z0-9_]+$`), range arguments are sanity-checked.

---

## 📌 Example prompts (frontend)

Paste into the input box:

* “Compare David Ortiz vs Torii Hunter HR in 2015”
* “Project David Ortiz wOBA next season”
* “Top 10 home_run in 2015” *(use the Leaderboard test chip if you wired it)*
* “Aaron Judge HR 2019–2022” *(line chart)*
* “Percentile of Ortiz wOBA in 2015 vs league” *(if you expose the endpoint in UI)*

> If you enabled the agent, it will map names → IDs and decide tool + chart_type. Otherwise use the **Test** buttons on the landing page.

---

## 🔒 Future: small VizSpec for user styling (optional)

Soon, the agent can return an optional **`viz`** block (bounded schema) to request presentation tweaks (line vs bar, palette tokens, smooth, stacked, labels). The backend validates this block; the frontend maps it to Nivo props.
This keeps data authoritative while letting users say “make it a stacked bar in teal.”

---

## 🧾 License

Personal/experimental. Decide license before public release.

---

## 👋 Contributing / Feedback

This is being actively iterated. If you spot a bug or want to propose a tool (e.g., rate per PA, comps, or what-if deltas), open an issue with:

* The query you tried
* The endpoint you hit (or the prompt)
* The JSON you received
* What you expected

---

## Appendix: Handy test IDs & stats

* **Players** (from the sample CSV):

  * Torii Hunter: `116338`
  * David Ortiz: `120074`
* **Stats** (snake_case): `home_run`, `woba`, `batting_avg`, `barrel_batted_rate`, `sprint_speed`, `plate_appearances`, …and most CSV headers.

---

Fire it up, load the CSV, and start asking baseball questions. ⚾️
