// frontend/src/utils/labels.js

export function applyLabelMapToText(text, labelMap) {
  if (!text || !labelMap) return text;
  let out = String(text);
  Object.keys(labelMap || {}).forEach((k) => {
    const rx = new RegExp(`\\b${k}\\b`, "g");
    out = out.replace(rx, String(labelMap[k]));
  });
  return out;
}

export function labelizeId(id, labelMap) {
  if (!id) return "";
  const s = String(id);

  if (s.startsWith("Projected ")) {
    const slug = s.slice("Projected ".length);
    return "Projected " + (labelMap?.[slug] || slug);
  }
  if (s.startsWith("Δ ")) {
    const slug = s.slice(2);
    return "Δ " + (labelMap?.[slug] || slug);
  }
  if (s.includes(" per ") && s.endsWith(" PA")) {
    const before = s.split(" per ")[0];
    const after = s.slice(before.length);
    return (labelMap?.[before] || before) + after;
  }
  if (s.includes(" percentile")) {
    const slug = s.split(" percentile")[0];
    return (labelMap?.[slug] || slug) + s.slice(slug.length);
  }
  if (s.includes(" histogram")) {
    const slug = s.split(" histogram")[0];
    return (labelMap?.[slug] || slug) + s.slice(slug.length);
  }
  return labelMap?.[s] || s;
}

export function fmtNumber(v) {
  const f = Number(v);
  if (Number.isNaN(f)) return String(v);
  if (Math.abs(f) >= 100) return f.toFixed(0);
  if (Math.abs(f) >= 10) return f.toFixed(1);
  if (Math.abs(f) >= 1) return String(Number(f.toFixed(3)));
  const s = f.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return s || "0";
}

export function isCategorical(series) {
  const first = series?.[0]?.data?.[0]?.x;
  return typeof first === "string";
}

export function getXStats(series) {
  const xs = (series || [])
    .flatMap((s) => (s.data || []).map((p) => p.x))
    .filter((v) => typeof v === "number" && !Number.isNaN(v))
    .sort((a, b) => a - b);
  if (!xs.length) return null;
  const ticks = Array.from(new Set(xs));
  return { min: ticks[0], max: ticks[ticks.length - 1], ticks };
}

export function sortSeriesByX(series) {
  return (series || []).map((s) => ({
    ...s,
    data: [...(s.data || [])].sort((a, b) => {
      const ax = typeof a.x === "number" ? a.x : Number(a.x);
      const bx = typeof b.x === "number" ? b.x : Number(b.x);
      return ax - bx;
    }),
  }));
}

export function buildBar(series) {
  const keys = (series || []).map((s) => s.id).filter(Boolean);
  const xSet = new Set();
  const rowMap = new Map();
  (series || []).forEach((s) => {
    (s.data || []).forEach((p) => {
      const x = p?.x;
      if (x == null) return;
      xSet.add(x);
      if (!rowMap.has(x)) rowMap.set(x, { x });
      rowMap.get(x)[s.id || "value"] = p?.y ?? null;
    });
  });
  const rows = Array.from(xSet).map((x) => rowMap.get(x));
  return { rows, keys };
}

export function orderRows(rows, meta) {
  if (!Array.isArray(rows)) return rows;
  if (Array.isArray(meta?.x_years) && meta.x_years.length) {
    const order = meta.x_years.map((n) => Number(n));
    const pos = new Map(order.map((v, i) => [v, i]));
    return [...rows].sort((a, b) => (pos.get(Number(a.x)) ?? Infinity) - (pos.get(Number(b.x)) ?? Infinity));
  }
  const allNumeric = rows.every((r) => !Number.isNaN(Number(r.x)));
  return allNumeric ? [...rows].sort((a, b) => Number(a.x) - Number(b.x)) : rows;
}
