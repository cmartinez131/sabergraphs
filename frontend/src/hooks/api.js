// src/hooks/api.js
// Frontend → Backend HTTP helpers
// Uses REACT_APP_API_URL at build time. Fallbacks:
// - On localhost → http://localhost:8000 (dev)
// - On any non-localhost origin → https://sabermetric-ai.onrender.com (prod safety)

const DEFAULT_DEV_API = "http://localhost:8000";
const DEFAULT_PROD_API = "https://sabermetric-ai.onrender.com";

function normalize(url) {
  return (url || "").trim().replace(/\/+$/, "");
}

function detectBase() {
  // 1) Build-time env (Vercel/CRA)
  const fromEnv = normalize(process?.env?.REACT_APP_API_URL);

  if (fromEnv) return fromEnv;

  // 2) Runtime safety: if we're not on localhost, never call localhost
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const isLocal =
      host === "localhost" || host === "127.0.0.1" || host === "::1";
    return isLocal ? DEFAULT_DEV_API : DEFAULT_PROD_API;
  }

  // 3) Very last resort (SSR or unknown)
  return DEFAULT_PROD_API;
}

export const API_BASE = detectBase();

// Expose for quick sanity checks in DevTools: window.API_BASE
if (typeof window !== "undefined") {
  window.API_BASE = API_BASE;
}

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
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
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
export function prompt(text, { debug = false } = {}) {
  const qs = debug ? "?debug=1" : "";
  return httpPost(`/api/prompt${qs}`, { text });
}
