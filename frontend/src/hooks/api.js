// frontend/src/hooks/api.js
const DEFAULT_DEV_API = "http://localhost:8000";
const DEFAULT_PROD_API = "https://sabermetric-ai.onrender.com";

function normalize(url) {
  return (url || "").trim().replace(/\/+$/, "");
}

const ENV_API = normalize(process.env.REACT_APP_API_URL || "");

function detectBase() {
  if (ENV_API) return ENV_API;

  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    const isLocal = h === "localhost" || h === "127.0.0.1" || h === "::1";
    return isLocal ? DEFAULT_DEV_API : DEFAULT_PROD_API;
  }
  return DEFAULT_PROD_API;
}

export const API_BASE = normalize(detectBase());

if (typeof window !== "undefined") {
  window.API_BASE = API_BASE;
}

// ---- Anonymous session id ----
function ensureSessionId() {
  try {
    let sid = localStorage.getItem("session_id");
    if (!sid) {
      sid =
        (typeof crypto !== "undefined" && crypto.randomUUID && crypto.randomUUID()) ||
        (Math.random().toString(36).slice(2) + Date.now().toString(36));
      localStorage.setItem("session_id", sid);
    }
    return sid;
  } catch {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
}
export const SESSION_ID = ensureSessionId();

// ---- HTTP helpers ----
async function httpGet(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json", "X-Session-Id": SESSION_ID },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `GET ${path} failed with ${res.status}`);
  }
  return res.json();
}

async function httpPost(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Session-Id": SESSION_ID,
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

async function httpDelete(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { Accept: "application/json", "X-Session-Id": SESSION_ID },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `DELETE ${path} failed with ${res.status}`);
  }
  return res.json();
}

// ---- Public API ----
export function health() { return httpGet(`/health`); }
export function compare(body) { return httpPost(`/api/compare`, body); }
export function predict(body) { return httpPost(`/api/predict`, body); }
export function prompt(text, { debug = false, hints = null } = {}) {
  const qs = debug ? "?debug=1" : "";
  const body = hints ? { text, hints } : { text };
  return httpPost(`/api/prompt${qs}`, body);
}

// ---- History API ----
export function historyRecent(limit = 20) {
  return httpGet(`/api/history/recent?limit=${encodeURIComponent(limit)}`);
}
export function historyLog({ prompt, payload, conversation_id, title }) {
  return httpPost(`/api/history/log`, { prompt, payload, conversation_id, title });
}
export function historyGet(conversationId) {
  return httpGet(`/api/history/${encodeURIComponent(conversationId)}`);
}
export function historyDelete(conversationId) {
  return httpDelete(`/api/history/${encodeURIComponent(conversationId)}`);
}
