// frontend/src/components/charts/ChartRenderer.jsx
import React, { useMemo } from "react";
import { ResponsiveLine } from "@nivo/line";
import { ResponsiveBar } from "@nivo/bar";
import { ResponsiveRadar } from "@nivo/radar";
import {
  fmtNumber,
  isCategorical,
  sortSeriesByX,
  getXStats,
  buildBar,
  orderRows,
  labelizeId,
} from "../../utils/labels";

/* ---------- Y-axis helpers (quant-friendly defaults) ----------

Override knobs you can send from the backend inside `meta`:
- meta.y_min: number       → hard minimum
- meta.y_max: number       → hard maximum
- meta.y_domain: [min,max] → hard domain
- meta.baseline_zero: bool → force 0 baseline when true

Auto rules if not explicitly set:
- If all y ≥ 0 → min = 0 (baseline at 0).
- If values look like rates (≤ 1.05) OR y_label mentions '%'/'rate'/AVG/OBP/wOBA:
    • max = 1.0
- If y_label mentions OPS or SLG:
    • max = max(1.2, ceil(1.05*maxData, to 0.1))
- Otherwise:
    • max = a "nice" ceiling slightly above the data (1/2/5 × 10^k).
---------------------------------------------------------------- */

function seriesMinMax(series) {
  let min = Infinity;
  let max = -Infinity;
  (series || []).forEach((s) =>
    (s.data || []).forEach((p) => {
      const y = Number(p?.y);
      if (!Number.isNaN(y) && Number.isFinite(y)) {
        if (y < min) min = y;
        if (y > max) max = y;
      }
    })
  );
  if (min === Infinity) min = 0;
  if (max === -Infinity) max = 0;
  return { min, max };
}

function looksLikeRate(yLabel, { min, max }) {
  const t = String(yLabel || "").toLowerCase();
  if (t.includes("%") || t.includes("rate")) return true;
  if (/\b(avg|ba|obp|woba|xwoba|xba|xobp|iso|babip)\b/i.test(t)) return true;
  // data-driven hint
  return max <= 1.05 && min >= 0;
}

function looksLikeOpsOrSlg(yLabel) {
  const t = String(yLabel || "").toLowerCase();
  return t.includes("ops") || t.includes("slg");
}

function niceCeil(n) {
  if (!Number.isFinite(n) || n <= 0) return 1;
  const exp = Math.floor(Math.log10(n));
  const base = 10 ** exp;
  const scaled = n / base;
  let step = 1;
  if (scaled <= 1) step = 1;
  else if (scaled <= 2) step = 2;
  else if (scaled <= 5) step = 5;
  else step = 10;
  return step * base;
}

function ceilToTenth(n) {
  return Math.ceil(n * 10) / 10;
}

function computeYMin(series, meta) {
  // hard overrides
  if (Array.isArray(meta?.y_domain) && meta.y_domain.length === 2) return meta.y_domain[0];
  if (typeof meta?.y_min === "number") return meta.y_min;
  if (typeof meta?.baseline_zero === "boolean") return meta.baseline_zero ? 0 : "auto";

  // auto: baseline at 0 when all values are non-negative
  const { min } = seriesMinMax(series);
  return min >= 0 ? 0 : "auto";
}

function computeYMax(series, meta) {
  // hard overrides
  if (Array.isArray(meta?.y_domain) && meta.y_domain.length === 2) return meta.y_domain[1];
  if (typeof meta?.y_max === "number") return meta.y_max;

  const stats = seriesMinMax(series);
  const yLabel = meta?.y_label || "";

  // rate-like scales → cap at 1.0 for clean headroom
  if (looksLikeRate(yLabel, stats)) return 1.0;

  // OPS/SLG often creep above 1.0 — use 1.2 floor or 10% padded tenth
  if (looksLikeOpsOrSlg(yLabel)) {
    const padded = ceilToTenth(Math.max(1.2, stats.max * 1.05));
    return padded;
  }

  // counts & everything else → "nice" ceiling with small headroom
  const padded = stats.max * 1.05; // 5% headroom
  return niceCeil(padded);
}

/* ---------------- Presentation ---------------- */

const BRAND_COLORS = [
  "#2ac9d9",
  "#7c6cff",
  "#ffd166",
  "#33d69f",
  "#ff6b6b",
  "#4895ef",
  "#80ed99",
  "#a78bfa",
  "#ef8354",
  "#06d6a0",
];

function Shell({ title, children }) {
  return (
    <div className="chart-surface">
      {title ? <div className="facet-title">{title}</div> : null}
      <div className="chart-box">{children}</div>
    </div>
  );
}

export default function ChartRenderer({ chartType, series, meta }) {
  const yLegend = meta?.y_label || "Value";
  const labelMap = meta?.label_map || {};

  // Build a literal-color Nivo theme from current CSS variables
  const theme = useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const STROKE = (css.getPropertyValue("--stroke") || "#d0d6ea").trim();
    const TEXT = (css.getPropertyValue("--text") || "#0d1220").trim();
    const TBG = (css.getPropertyValue("--tooltip-bg") || "#ffffff").trim();
    return {
      textColor: TEXT,
      fontSize: 12,
      axis: {
        ticks: { text: { fill: TEXT } },
        legend: { text: { fill: TEXT } },
        domain: { line: { stroke: STROKE } },
      },
      grid: { line: { stroke: STROKE } },
      legends: { text: { fill: TEXT } },
      tooltip: {
        container: {
          background: TBG,
          color: TEXT,
          border: `1px solid ${STROKE}`,
          borderRadius: 12,
          padding: 10,
          boxShadow: "var(--shadow)",
        },
      },
    };
  }, []);

  function deriveTitle() {
    if (meta?.title) return meta.title;
    if (chartType === "bar" && Array.isArray(series) && series.length === 1) {
      const id = series[0]?.id;
      const x = series[0]?.data?.[0]?.x;
      if (id) {
        const niceId = labelizeId(id, labelMap);
        return x ? `${niceId} — ${x}` : niceId;
      }
    }
    return null;
  }

  /* ---------------- Radar ---------------- */
  if (chartType === "radar") {
    const data = Array.isArray(series) ? series : [];
    const prettyData = data.map((row) => {
      const statSlug = row?.stat;
      const statLabel = labelMap?.[statSlug] || statSlug;
      return { ...row, stat: statLabel };
    });
    const allKeys = new Set();
    prettyData.forEach((row) =>
      Object.keys(row).forEach((k) => k !== "stat" && allKeys.add(k))
    );
    const keys = Array.from(allKeys);

    return (
      <Shell title={deriveTitle()}>
        <ResponsiveRadar
          data={prettyData}
          keys={keys}
          indexBy="stat"
          theme={theme}
          margin={{ top: 40, right: 60, bottom: 60, left: 60 }}
          curve="linearClosed"
          gridLevels={5}
          dotSize={3}
          dotBorderWidth={1}
          colors={BRAND_COLORS}
          animate
          motionConfig="gentle"
          legends={[
            {
              anchor: "bottom",
              direction: "row",
              translateY: 40,
              itemWidth: 100,
              itemHeight: 16,
              symbolSize: 10,
              symbolShape: "circle",
            },
          ]}
          valueFormat={(v) => fmtNumber(v)}
        />
      </Shell>
    );
  }

  /* ---------------- Bar ---------------- */
  if (chartType === "bar") {
    const prettySeries = (series || []).map((s) => ({
      ...s,
      id: labelizeId(s.id, labelMap),
    }));
    const { rows: rawRows, keys } = buildBar(prettySeries);
    const rows = orderRows(rawRows, meta);
    const groupMode = meta?.layout === "stacked" ? "stacked" : "grouped";

    const firstX = rows?.[0]?.x;
    const xLegend =
      (Array.isArray(meta?.x_years) && meta.x_years.length) || typeof firstX === "number"
        ? "Year"
        : meta?.mode === "players_by_stat" || typeof firstX === "string"
        ? "Player"
        : "Category";

    const tickRotation = rows && rows.length > 8 ? -25 : 0;

    // Allocate explicit room for the legend *below* the x-axis text
    const LEGEND_H = 22;
    const GAP = 12;
    const AXIS_LABEL = 42;
    const TICKS_AREA = tickRotation < 0 ? 34 : 24;
    const bottomMargin = AXIS_LABEL + TICKS_AREA + LEGEND_H + GAP;

    // y-domain
    const yMinBar = computeYMin(prettySeries, meta);
    const yMaxBar = computeYMax(prettySeries, meta);

    return (
      <Shell title={deriveTitle()}>
        <ResponsiveBar
          data={rows}
          keys={keys.length ? keys : [prettySeries?.[0]?.id || "value"]}
          indexBy="x"
          groupMode={groupMode}
          margin={{ top: 20, right: 28, bottom: bottomMargin, left: 56 }}
          padding={0.3}
          theme={theme}
          enableGridY
          enableGridX
          valueFormat={(v) => fmtNumber(v)}
          yScale={{ type: "linear", min: yMinBar, max: yMaxBar }}
          axisBottom={{
            tickSize: 0,
            tickPadding: 10,
            tickRotation,
            legend: xLegend,
            legendOffset: AXIS_LABEL,
            legendPosition: "middle",
          }}
          axisLeft={{
            tickSize: 0,
            tickPadding: 6,
            legend: yLegend,
            legendOffset: -46,
            legendPosition: "middle",
          }}
          labelSkipHeight={14}
          labelSkipWidth={14}
          labelTextColor="var(--text)"
          colors={BRAND_COLORS}
          borderColor={{ from: "color", modifiers: [["darker", 1.4]] }}
          legends={[
            {
              dataFrom: "keys",
              anchor: "bottom",
              direction: "row",
              translateY: bottomMargin - (LEGEND_H + Math.max(GAP - 4, 6)),
              itemWidth: 110,
              itemHeight: LEGEND_H,
              symbolSize: 10,
              symbolShape: "circle",
            },
          ]}
          tooltip={({ id, value, indexValue }) => (
            <div style={{ padding: 6 }}>
              <strong>{String(id)}</strong> — {String(indexValue)}
              <div style={{ opacity: 0.8 }}>{fmtNumber(value)}</div>
            </div>
          )}
        />
      </Shell>
    );
  }

  /* ---------------- Line ---------------- */
  const categorical = isCategorical(series);
  const seriesForLine = categorical
    ? (series || []).map((s) => ({ ...s, id: labelizeId(s.id, labelMap) }))
    : sortSeriesByX(series).map((s) => ({ ...s, id: labelizeId(s.id, labelMap) }));

  const metaYears = Array.isArray(meta?.x_years)
    ? meta.x_years
        .map((n) => Number(n))
        .filter((n) => !Number.isNaN(n))
        .sort((a, b) => a - b)
    : null;

  const xstats = categorical ? null : getXStats(seriesForLine);
  const minX = categorical ? undefined : metaYears ? metaYears[0] : xstats?.min ?? "auto";
  const maxX = categorical ? undefined : metaYears ? metaYears[metaYears.length - 1] : xstats?.max ?? "auto";
  const tickValues = categorical ? undefined : metaYears || xstats?.ticks;

  const yMinLine = computeYMin(seriesForLine, meta);
  const yMaxLine = computeYMax(seriesForLine, meta);

  function BandLayer(props) {
    try {
      const lm = labelMap || {};
      const p10Id = lm["p10"] || "p10";
      const p90Id = lm["p90"] || "p90";
      const p10 = (props.series || []).find((s) => s.id === p10Id);
      const p90 = (props.series || []).find((s) => s.id === p90Id);
      if (!p10 || !p90) return null;

      const up = (p90.data || []).map((d) => [d.x, d.y]);
      const dn = (p10.data || [])
        .slice()
        .reverse()
        .map((d) => [d.x, d.y]);
      if (!up.length || !dn.length) return null;

      const pts = up.concat(dn);
      const d =
        pts
          .map((pt, i) => (i === 0 ? `M ${pt[0]} ${pt[1]}` : `L ${pt[0]} ${pt[1]}`))
          .join(" ") + " Z";
      return <path d={d} fill="var(--band-fill, rgba(127,127,127,0.18))" stroke="none" />;
    } catch {
      return null;
    }
  }

  // extra bottom space for legend under the x-axis label
  const LINE_AXIS_LABEL = 44;
  const LINE_TICKS_AREA = 26;
  const LINE_LEGEND_H = 22;
  const LINE_GAP = 12;
  const lineBottom = LINE_AXIS_LABEL + LINE_TICKS_AREA + LINE_LEGEND_H + LINE_GAP;

  return (
    <Shell title={deriveTitle()}>
      <ResponsiveLine
        data={seriesForLine}
        theme={theme}
        margin={{ top: 20, right: 28, bottom: lineBottom, left: 56 }}
        xScale={categorical ? { type: "point" } : { type: "linear", min: minX, max: maxX }}
        yScale={{ type: "linear", min: yMinLine, max: yMaxLine }}
        curve="monotoneX"
        enablePoints
        pointSize={7}
        enableArea
        areaOpacity={0.25}
        colors={BRAND_COLORS}
        enableGridX
        enableGridY
        axisBottom={{
          tickSize: 0,
          tickPadding: 10,
          tickValues,
          format: (v) => (typeof v === "number" ? String(v) : v),
          legend: categorical ? "Category" : "Season",
          legendOffset: LINE_AXIS_LABEL,
          legendPosition: "middle",
        }}
        axisLeft={{
          tickSize: 0,
          tickPadding: 6,
          legend: yLegend,
          legendOffset: -46,
          legendPosition: "middle",
        }}
        legends={[
          {
            dataFrom: "series",
            anchor: "bottom",
            direction: "row",
            translateY: lineBottom - (LINE_LEGEND_H + Math.max(LINE_GAP - 4, 6)),
            itemWidth: 140,
            itemHeight: LINE_LEGEND_H,
            symbolSize: 10,
            symbolShape: "circle",
            toggleSerie: true,
          },
        ]}
        useMesh
        motionConfig="gentle"
        tooltip={({ point }) => {
          const seriesId = point?.serieId ?? point?.serie?.id ?? point?.id ?? "Series";
          const x = point?.data?.xFormatted ?? point?.data?.x;
          const y = point?.data?.yFormatted ?? point?.data?.y;
          return (
            <div style={{ padding: 6 }}>
              <div style={{ fontWeight: 600 }}>{String(seriesId)}</div>
              <div>
                {String(x)}: {fmtNumber(y)}
              </div>
            </div>
          );
        }}
        layers={[
          "grid",
          "markers",
          "axes",
          BandLayer,
          "areas",
          "lines",
          "points",
          "slices",
          "mesh",
          "legends",
        ]}
      />
    </Shell>
  );
}
