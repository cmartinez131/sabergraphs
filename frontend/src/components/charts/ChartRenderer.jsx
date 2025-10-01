import React from "react";
import { ResponsiveLine } from "@nivo/line";
import { ResponsiveBar } from "@nivo/bar";
import { ResponsiveRadar } from "@nivo/radar";
import nivoTheme from "../../utils/nivoTheme";
import {
  fmtNumber,
  isCategorical,
  sortSeriesByX,
  getXStats,
  buildBar,
  orderRows,
  labelizeId,
} from "../../utils/labels";

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

  // Radar
  if (chartType === "radar") {
    const data = Array.isArray(series) ? series : [];
    const prettyData = data.map((row) => {
      const statSlug = row?.stat;
      const statLabel = labelMap?.[statSlug] || statSlug;
      return { ...row, stat: statLabel };
    });
    const allKeys = new Set();
    prettyData.forEach((row) => Object.keys(row).forEach((k) => k !== "stat" && allKeys.add(k)));
    const keys = Array.from(allKeys);

    return (
      <Shell title={deriveTitle()}>
        <ResponsiveRadar
          data={prettyData}
          keys={keys}
          indexBy="stat"
          theme={nivoTheme}
          margin={{ top: 40, right: 60, bottom: 60, left: 60 }}
          curve="linearClosed"
          gridLevels={5}
          dotSize={3}
          dotBorderWidth={1}
          colors={{ scheme: "category10" }}
          animate
          motionConfig="gentle"
          legends={[{ anchor: "bottom", direction: "row", translateY: 40, itemWidth: 100, itemHeight: 16, symbolSize: 10, symbolShape: "circle" }]}
          valueFormat={(v) => fmtNumber(v)}
        />
      </Shell>
    );
  }

  // Bar
  if (chartType === "bar") {
    const prettySeries = (series || []).map((s) => ({ ...s, id: labelizeId(s.id, labelMap) }));
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

    return (
      <Shell title={deriveTitle()}>
        <ResponsiveBar
          data={rows}
          keys={keys.length ? keys : [prettySeries?.[0]?.id || "value"]}
          indexBy="x"
          groupMode={groupMode}
          margin={{ top: 20, right: 28, bottom: 70, left: 56 }}
          padding={0.3}
          theme={nivoTheme}
          enableGridY
          valueFormat={(v) => fmtNumber(v)}
          axisBottom={{ tickSize: 0, tickPadding: 10, legend: xLegend, legendOffset: 42, legendPosition: "middle" }}
          axisLeft={{ tickSize: 0, tickPadding: 6, legend: yLegend, legendOffset: -46, legendPosition: "middle" }}
          labelSkipHeight={14}
          labelTextColor="var(--text)"
          legends={[{ dataFrom: "keys", anchor: "top-right", direction: "column", translateX: 12, itemWidth: 120, itemHeight: 20, symbolSize: 10, symbolShape: "circle" }]}
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

  // Line
  const categorical = isCategorical(series);
  const seriesForLine = categorical
    ? (series || []).map((s) => ({ ...s, id: labelizeId(s.id, labelMap) }))
    : sortSeriesByX(series).map((s) => ({ ...s, id: labelizeId(s.id, labelMap) }));

  const metaYears = Array.isArray(meta?.x_years)
    ? meta.x_years.map((n) => Number(n)).filter((n) => !Number.isNaN(n)).sort((a, b) => a - b)
    : null;

  const xstats = categorical ? null : getXStats(seriesForLine);
  const minX = categorical ? undefined : (metaYears ? metaYears[0] : xstats?.min ?? "auto");
  const maxX = categorical ? undefined : (metaYears ? metaYears[metaYears.length - 1] : xstats?.max ?? "auto");
  const tickValues = categorical ? undefined : (metaYears || xstats?.ticks);

  function BandLayer(props) {
    try {
      const lm = labelMap || {};
      const p10Id = lm["p10"] || "p10";
      const p90Id = lm["p90"] || "p90";
      const p10 = (props.series || []).find((s) => s.id === p10Id);
      const p90 = (props.series || []).find((s) => s.id === p90Id);
      if (!p10 || !p90) return null;

      const up = (p90.data || []).map((d) => [d.x, d.y]);
      const dn = (p10.data || []).slice().reverse().map((d) => [d.x, d.y]);
      if (!up.length || !dn.length) return null;

      const pts = up.concat(dn);
      const d = pts.map((pt, i) => (i === 0 ? `M ${pt[0]} ${pt[1]}` : `L ${pt[0]} ${pt[1]}`)).join(" ") + " Z";
      return <path d={d} fill="var(--band-fill, rgba(127,127,127,0.18))" stroke="none" />;
    } catch {
      return null;
    }
  }

  return (
    <Shell title={deriveTitle()}>
      <ResponsiveLine
        data={seriesForLine}
        theme={nivoTheme}
        margin={{ top: 20, right: 28, bottom: 70, left: 56 }}
        xScale={categorical ? { type: "point" } : { type: "linear", min: minX, max: maxX }}
        yScale={{ type: "linear", min: "auto", max: "auto" }}
        curve="monotoneX"
        enablePoints
        pointSize={7}
        enableArea
        areaOpacity={0.25}
        colors={{ scheme: "category10" }}
        axisBottom={{
          tickSize: 0,
          tickPadding: 10,
          tickValues,
          format: (v) => (typeof v === "number" ? String(v) : v),
          legend: categorical ? "Category" : "Season",
          legendOffset: 44,
          legendPosition: "middle",
        }}
        axisLeft={{ tickSize: 0, tickPadding: 6, legend: "Value", legendOffset: -46, legendPosition: "middle" }}
        legends={[{ dataFrom: "series", anchor: "top-right", direction: "column", translateX: 12, itemWidth: 160, itemHeight: 16, symbolSize: 10, symbolShape: "circle", toggleSerie: true }]}
        useMesh
        motionConfig="gentle"
        tooltip={({ point }) => {
          const seriesId = point?.serieId ?? point?.serie?.id ?? point?.id ?? "Series";
          const x = point?.data?.xFormatted ?? point?.data?.x;
          const y = point?.data?.yFormatted ?? point?.data?.y;
          return (
            <div style={{ padding: 6 }}>
              <div style={{ fontWeight: 600 }}>{String(seriesId)}</div>
              <div>{String(x)}: {fmtNumber(y)}</div>
            </div>
          );
        }}
        layers={["grid", "markers", "axes", BandLayer, "areas", "lines", "points", "slices", "mesh", "legends"]}
      />
    </Shell>
  );
}
