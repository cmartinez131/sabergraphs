function csvEscape(v) {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCSV(headers, rows) {
  const head = headers.map(csvEscape).join(",");
  const body = rows.map((r) => r.map((c) => csvEscape(c))).join("\n");
  return head + "\n" + body;
}

function formatCsvCell(v) {
  if (v === null || v === undefined) return "";
  const n = Number(v);
  if (!Number.isNaN(n) && Number.isFinite(n)) return n.toFixed(3).replace(/\.?0+$/, "");
  return String(v);
}

export function sanitizeFileName(s) {
  return String(s || "chart").replace(/[^\w\d\-]+/g, "_").slice(0, 80);
}

export function downloadURL(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function downloadTextAsFile(text, filename, mime = "text/csv;charset=utf-8;") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  downloadURL(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// axis/title helpers
function guessXHeader(series, meta) {
  const firstX = series?.[0]?.data?.[0]?.x;
  if (typeof firstX === "number") return "Year";
  if (meta?.mode === "players_by_stat" || typeof firstX === "string") return "Player";
  return "Category";
}

function labelizeIdSimple(id, labelMap) {
  if (!id) return "";
  return labelMap?.[id] || id;
}

// builders
export function csvFromBarOrLine(inSeries, meta) {
  const xHeader = guessXHeader(inSeries, meta);
  let xs = Array.from(new Set((inSeries || []).flatMap((s) => (s.data || []).map((p) => p.x))));
  const metaYears = Array.isArray(meta?.x_years) ? meta.x_years.map((n) => Number(n)) : null;
  if (metaYears && metaYears.length) {
    const pos = new Map(metaYears.map((v, i) => [v, i]));
    xs.sort((a, b) => (pos.get(Number(a)) ?? Infinity) - (pos.get(Number(b)) ?? Infinity));
  } else if (xs.every((x) => !Number.isNaN(Number(x)))) {
    xs.sort((a, b) => Number(a) - Number(b));
  }

  if ((inSeries || []).length === 1) {
    const s = inSeries[0];
    const yLabel = labelizeIdSimple(s.id, meta?.label_map || {});
    const rows = xs.map((x) => {
      const hit = (s.data || []).find((p) => p.x === x);
      return [x, hit ? formatCsvCell(hit.y) : ""];
    });
    return toCSV([xHeader, yLabel], rows);
  }

  const lm = meta?.label_map || {};
  const ids = (inSeries || []).map((s) => labelizeIdSimple(s.id, lm));
  const rows = xs.map((x) => {
    const row = [x];
    (inSeries || []).forEach((s) => {
      const hit = (s.data || []).find((p) => p.x === x);
      row.push(hit ? formatCsvCell(hit.y) : "");
    });
    return row;
  });
  return toCSV([xHeader, ...ids], rows);
}

export function csvFromRadar(inSeries, labelMap) {
  const keys = new Set();
  (inSeries || []).forEach((row) => {
    Object.keys(row || {}).forEach((k) => k !== "stat" && keys.add(k));
  });
  const cols = Array.from(keys);
  const headers = ["Stat", ...cols];
  const rows = (inSeries || []).map((row) => [
    labelMap?.[row.stat] || row.stat,
    ...cols.map((k) => (row[k] == null ? "" : formatCsvCell(row[k]))),
  ]);
  return toCSV(headers, rows);
}

export function csvFromFacets(inFacets) {
  const blocks = [];
  (inFacets || []).forEach((f) => {
    let block = "";
    if ((f?.chart_type || "line") === "radar") {
      block = csvFromRadar(f.series || [], f?.meta?.label_map || {});
    } else {
      block = csvFromBarOrLine(f.series || [], f.meta || {});
    }
    blocks.push(`# ${f?.title || "Facet"}`, block);
  });
  return blocks.join("\n\n");
}
