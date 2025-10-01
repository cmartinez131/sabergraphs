// frontend/src/hooks/api.js
// CRA/Render/Vercel friendly. Set REACT_APP_API_URL in Vercel to your backend URL.
// Fallback is http://localhost:8000 for local dev.

const API_BASE =
  (typeof process !== "undefined" &&
    process.env &&
    process.env.REACT_APP_API_URL &&
    process.env.REACT_APP_API_URL.replace(/\/+$/, "")) ||
  "http://localhost:8000";

async function httpGet(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `GET ${path} failed with ${res.status}`);
  }
  return res.json();
}

async function httpPost(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000); // 30s safety timeout
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `POST ${path} failed with ${res.status}`);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Public API
export function health() {
  return httpGet(`/`);
}

export function compare(body) {
  return httpPost(`/api/compare`, body);
}

export function predict(body) {
  return httpPost(`/api/predict`, body);
}

// Natural-language prompt endpoint (agent-driven)
export function prompt(text, { debug = false } = {}) {
  const qs = debug ? "?debug=1" : "";
  return httpPost(`/api/prompt${qs}`, { text });
}
