#!/usr/bin/env bash
set -euo pipefail

# === Config (override with env vars if needed) ===
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"   # <-- CRA default

# Pick docker compose command
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi

echo "==> Bringing up containers (if not already running)…"
$DC up -d

echo "==> Waiting for backend: $BACKEND_URL/"
for i in {1..60}; do
  if curl -fsS "$BACKEND_URL/" >/dev/null; then
    echo "    Backend is up."
    break
  fi
  sleep 0.5
  if [ "$i" -eq 60 ]; then
    echo "Backend did not become ready."
    docker logs sabermetric_backend --tail 200 || true
    exit 1
  fi
done

echo "==> Hitting /api/compare …"
COMPARE_PAYLOAD='{"player_ids":[116338,120074],"stat":"home_run","year":2015}'
if curl -fsS -X POST "$BACKEND_URL/api/compare" -H "Content-Type: application/json" -d "$COMPARE_PAYLOAD" | grep -q '"series"'; then
  echo "    /api/compare OK."
else
  echo "    /api/compare FAILED."
  exit 1
fi

echo "==> Hitting /api/predict …"
PREDICT_PAYLOAD='{"player_id":120074,"stat":"woba","years":3}'
if curl -fsS -X POST "$BACKEND_URL/api/predict" -H "Content-Type: application/json" -d "$PREDICT_PAYLOAD" | grep -q '"series"'; then
  echo "    /api/predict OK."
else
  echo "    /api/predict FAILED."
  exit 1
fi

echo "==> Waiting for frontend: $FRONTEND_URL"
for i in {1..60}; do
  # CRA returns HTML; just ensure we get a page back
  if curl -fsS "$FRONTEND_URL" | grep -qiE '<!doctype html|React App'; then
    echo "    Frontend is up."
    echo "✅ All basic checks passed."
    exit 0
  fi
  sleep 0.5
done

echo "Frontend did not become ready."
docker logs sabermetric_frontend --tail 200 || true
exit 1
