// frontend/src/hooks/history.js
// Simple local history for recent charts (prompts + payloads)

const KEY = "saber_history_v1";
const CAP = 40; // keep last N entries

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = JSON.parse(raw || "[]");
    if (!Array.isArray(arr)) return [];
    // newest first
    return arr.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  } catch {
    return [];
  }
}

function write(items) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items.slice(0, CAP)));
  } catch {}
}

function mkId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function deriveTitleFrom(payload, prompt) {
  const t = payload?.meta?.title || "";
  if (t && t.trim()) return t.trim();
  // Fallback: compact the prompt
  const p = String(prompt || "").replace(/\s+/g, " ").trim();
  return p.slice(0, 80) || "Chart";
}

export function addToHistory({ prompt, payload, title }) {
  const now = Date.now();
  const items = read();
  const item = {
    id: mkId(),
    prompt: String(prompt || ""),
    title: String(title || deriveTitleFrom(payload, prompt)),
    chart_type: payload?.chart_type || "bar",
    meta: payload?.meta || {},
    series: payload?.series || [],
    facets: payload?.facets || null,
    narration: payload?.narration || "",
    updated_at: now,
    ai_source: payload?.ai_source || "",
  };
  items.unshift(item);
  write(items);
  return item;
}

export function getRecent(limit = 20) {
  return read().slice(0, limit);
}

export function getById(id) {
  return read().find((x) => x.id === id) || null;
}

export function clearHistory() {
  localStorage.removeItem(KEY);
}

export function timeAgo(ts) {
  const s = Math.floor((Date.now() - (ts || 0)) / 1000);
  if (s < 60) return "now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}
