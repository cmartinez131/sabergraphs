import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toPng } from "html-to-image";
import { health as apiHealth, prompt as apiPrompt } from "../hooks/api";
import NavBar from "../components/layout/NavBar";
import Sidebar from "../components/layout/Sidebar";
import StatusPill from "../components/common/StatusPill";
import ChartSkeleton from "../components/common/ChartSkeleton";
import ChartRenderer from "../components/charts/ChartRenderer";
import {
  csvFromBarOrLine,
  csvFromRadar,
  csvFromFacets,
  sanitizeFileName,
  downloadTextAsFile,
  downloadURL,
} from "../utils/csv";
import { applyLabelMapToText } from "../utils/labels";

const months = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"];
function genLine() {
  return [
    {
      id: "Metric",
      data: months.map((m, i) => {
        const base = 55 + 28 * Math.sin((i / months.length) * Math.PI * 2);
        const jitter = Math.random() * 12 - 6;
        return { x: m, y: Math.max(8, Math.min(98, base + jitter)) };
      }),
    },
  ];
}

export default function Home() {
  const [backend, setBackend] = useState({ ok: null, text: "Connecting..." });
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasChart, setHasChart] = useState(false);
  const [chartType, setChartType] = useState("line");
  const [series, setSeries] = useState(genLine());
  const [facets, setFacets] = useState(null);
  const [meta, setMeta] = useState({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chartSummary, setChartSummary] = useState("");
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "dark");

  const heroInputRef = useRef(null);
  const composerInputRef = useRef(null);
  const chartNodeRef = useRef(null);
  const navigate = useNavigate();

  const active = loading || hasChart;
  const loggedIn = false;

  const conversations = useMemo(
    () => [
      { id: "c1", title: "Judge vs. Ohtani (last 3 yrs)", updated: "Today" },
      { id: "c2", title: "Volpe OPS Projection", updated: "Yesterday" },
      { id: "c3", title: "Yankees odds by week", updated: "2d ago" },
      { id: "c4", title: "Top Barrel% since 2019", updated: "3d ago" },
    ],
    []
  );

  // ---------- Health check ----------
  useEffect(() => {
    let cancelled = false;
    apiHealth()
      .then((d) => {
        if (cancelled) return;
        const msg = d?.message || "";
        const ok = d?.status === "ok" || /running|ready|hello|ok/i.test(msg);
        setBackend({ ok, text: ok ? "Running" : (msg || "Connecting...") });
      })
      .catch(() => {
        if (cancelled) return;
        setBackend({ ok: false, text: "Could not connect to backend." });
      });
    return () => { cancelled = true; };
  }, []);

  // Follow OS theme changes if user hasn't manually chosen
  useEffect(() => {
    if (localStorage.getItem("theme")) return;
    if (!window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e) => {
      const next = e.matches ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      setTheme(next);
    };
    try {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    } catch {
      mql.addListener(onChange);
      return () => mql.removeListener(onChange);
    }
  }, []);

  const promptGroups = useMemo(
    () => ({
      "Compare players": [
        "Judge vs Soto home runs in 2025",
        "Trout vs Harper batting average in 2019",
        "Compare Carroll, Witt Jr., and Tatis Jr. sprint speed in 2024",
        "Compare Acuña, Soto, and Betts on OPS and HR in 2023",
        "Compare Lindor and Marte on steals and runs from 2020 to 2025",
      ],
      "Project future stats": [
        "Forecast Aaron Judge OPS for the next 6 years",
        "Estimate Shohei Ohtani HR for the next 3 years",
        "Forecast Juan Soto SLG for the next 3 years",
        "Project Elly De La Cruz stolen bases over the next 4 years",
        "Over the next 5 years, project Julio Rodríguez HR",
      ],
      "Get stat leaderboards and rankings": [
        "Hit by pitch leaders 2017–2019 (sum)",
        "top 5 players in home runs in 2025",
        "Top 10 barrel% in 2022",
        "Lowest 10 K% in 2022",
        "bottom 10 strikeout % in 2023",
        "leader in single season slugging percentage from 2020 to 2025",
        "top 12 stolen bases totals between 2024 and 2025",
        "top 8 OPS average from 2022 to 2024",
        "single-season HR leaders 2020-2025",
      ],
      "Analyze player trends": [
        "Juan Soto hits from 2019 to 2025",
        "K% by season for Ronald Acuña Jr. 2019–2023",
        "Stanton slugging % from 2022 to 2025",
        "bregman home runs 2015 to 2025",
      ],
      "Look up a single stat": [
        "Shohei Ohtani OPS in 2024",
        "Mookie Betts wOBA in 2020",
        "Soto Steals in 2025",
        "Most RBIs in 2019"
      ],
    }),
    []
  );

  function toggleTheme() {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    setTheme(next);
  }

  function runDemo() {
    setLoading(true);
    setHasChart(false);
    setChartSummary("");
    setFacets(null);
    setMeta({});
    setTimeout(() => {
      setSeries(genLine());
      setChartType("line");
      setLoading(false);
      setHasChart(true);
      setChartSummary("Quick take: the trend peaks mid-season before cooling off into September.");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }, 800);
  }

  async function callPrompt(text) {
    setLoading(true);
    setHasChart(false);
    setChartSummary("");
    setFacets(null);
    setMeta({});
    try {
      const res = await apiPrompt(text);
      if (res.chart_type === "facet") {
        setChartType("facet");
        const fac = (res.facets || []).map((f) => ({
          ...f,
          title: applyLabelMapToText(f.title, f?.meta?.label_map || {}),
        }));
        setFacets(fac);
        setSeries([]);
      } else {
        setChartType(res.chart_type || "bar");
        setSeries(res.series || []);
      }
      const incomingMeta = res.meta || {};
      if (incomingMeta.title) {
        incomingMeta.title = applyLabelMapToText(incomingMeta.title, incomingMeta.label_map || {});
      }
      setMeta(incomingMeta);
      setChartSummary(res.narration || "");
      setHasChart(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      alert("Prompt failed: " + e.message);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    const q = (query || "").trim();
    if (!q) return;
    if (/^\s*(see|run)\s+(a\s+)?(quick\s+)?demo\s*$/i.test(q) || /^\s*demo\s*$/i.test(q)) {
      runDemo();
      return;
    }
    callPrompt(q);
  }

  function resetUI() {
    setLoading(false);
    setHasChart(false);
    setChartSummary("");
    setQuery("");
    setSidebarOpen(false);
    setFacets(null);
    setMeta({});
    navigate("/");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleFill(text) {
    setQuery(text);
    const target = (loading || hasChart) ? composerInputRef.current : heroInputRef.current;
    if (target) target.focus();
  }

  const backendLabel = backend.ok ? "Running" : backend.text;
  const backendState = backend.ok ? "ok" : backend.ok === false ? "error" : "warn";

  /* ---------- Exports ---------- */
  async function exportPNG() {
    if (!chartNodeRef.current) return;

    // For facets, capture the whole grid. Otherwise capture the single chart surface (title + chart).
    const selector = chartType === "facet" ? ".facet-grid" : ".chart-surface";
    const surface =
      chartNodeRef.current.querySelector(selector) || chartNodeRef.current;

    // Apply bright, print-friendly export skin and lock size via CSS
    surface.classList.add("export-snapshot");

    // Pin key CSS vars inline so the cloned SVG resolves them
    const css = getComputedStyle(surface);
    ["--stroke", "--text", "--tooltip-bg"].forEach((v) => {
      surface.style.setProperty(v, css.getPropertyValue(v));
    });

    try {
      const dataUrl = await toPng(surface, {
        pixelRatio: 2,
        backgroundColor: "#ffffff",
        cacheBust: true,
      });

      const base = sanitizeFileName(meta?.title || "sabermetric_ai_chart");
      downloadURL(dataUrl, `${base}.png`);
    } catch (e) {
      console.error("PNG export failed", e);
      alert("PNG export failed (see console).");
    } finally {
      surface.classList.remove("export-snapshot");
      ["--stroke", "--text", "--tooltip-bg"].forEach((v) =>
        surface.style.removeProperty(v)
      );
    }
  }

  function exportCSV() {
    let csv = "";
    if (chartType === "facet" && Array.isArray(facets) && facets.length) {
      csv = csvFromFacets(facets);
    } else if (chartType === "radar") {
      csv = csvFromRadar(series, meta?.label_map || {});
    } else {
      csv = csvFromBarOrLine(series, meta || {});
    }
    const base = sanitizeFileName(meta?.title || "sabermetric_ai_chart");
    downloadTextAsFile(csv, `${base}.csv`);
  }

  return (
    <div className={`App ${active ? "is-active" : "lock"} ${sidebarOpen ? "sidebar-open" : ""}`}>
      {/* Background */}
      <div className="bg">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="grain" />
      </div>

      {/* Sidebar */}
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        conversations={conversations}
        onSelectConversation={(c) => {
          setSidebarOpen(false);
          setQuery(c.title);
          const target = (loading || hasChart) ? composerInputRef.current : heroInputRef.current;
          if (target) target.focus();
        }}
        loggedIn={loggedIn}
        onNewChat={resetUI}
      />

      {/* Navbar */}
      <NavBar
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSidebar={() => setSidebarOpen(true)}
        onHomeClick={resetUI}
      />

      {/* Landing (hidden once active) */}
      {!active && (
        <main className="container">
          <section className="hero glass">
            <h1>
              Ask baseball questions.
              <br />
              <span className="accent">See data. Get insights.</span>
            </h1>
            <p className="sub">Natural language → analytics, projections, and beautiful charts.</p>

            <div className="status-row">
              <div className="status-card glass">
                <h2>Getting started</h2>
                <ul className="bullets">
                  <li>Ask a baseball question (e.g., “Who hit the most home runs from 2020 to 2025?”) or click starter prompt below.</li>
                  <li>Compare players (e.g., “Judge vs Soto HR 2025”).</li>
                  <li>Query for projections (e.g., “Estimate Judge OPS for the next 5 years”).</li>
                  <li>Available stats: AB, PA, H, 1B/2B/3B, HR, SO, BB, K%, BB%, AVG, SLG, OBP, OPS, RBI, LOB, TB, HBP, GIDP, called strikes, swinging strikes, and more</li>
                  <li>Export results as CSV file or PNG image of the chart.</li>
                </ul>
              </div>

              <div className="status-card glass">
                <h2>Service Status</h2>
                <div className="rows">
                  <div className="row"><span>Frontend</span><StatusPill label="Running" state="ok" /></div>
                  <div className="row">
                    <span>Backend</span>
                    <StatusPill label={backendLabel} state={backendState} />
                  </div>
                  <div className="row"><span>Database</span><StatusPill label="Running" state="ok" /></div>
                  <p className="muted" style={{ marginTop: 8 }}>*Only 2015-2025 batter data available</p>
                </div>
              </div>
            </div>

            <form className="prompt" onSubmit={onSubmit}>
              <input
                ref={heroInputRef}
                className="prompt-input big"
                placeholder="Top 5 players in home runs in 2025"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Ask Sabermetric AI"
              />
              <button className="btn primary" type="submit">Ask AI</button>
            </form>

            <div className="chip-groups">
              {Object.entries(promptGroups).map(([group, prompts]) => (
                <div key={group} className="chip-group">
                  <div className="chip-group-title">{group}</div>
                  <div className="chips">
                    {prompts.map((text) => (
                      <button
                        key={text}
                        className="chip"
                        type="button"
                        onClick={() => handleFill(text)}
                        title="Fill input"
                      >
                        {text}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </main>
      )}

      {/* Stage */}
      {active && (
        <main className="container">
          <section className="stage">
            <div className="chart-card glass">
              <div className="chart-content">
                {loading ? (
                  <ChartSkeleton />
                ) : hasChart ? (
                  <>
                    <div ref={chartNodeRef}>
                      {chartType === "facet" ? (
                        <div className="facet-grid">
                          {(facets || []).map((f, i) => (
                            <div key={i} className="facet-card glass">
                              <div className="facet-title">{f.title || `Facet ${i + 1}`}</div>
                              <ChartRenderer
                                chartType={f.chart_type || "line"}
                                series={f.series || []}
                                meta={f.meta || {}}
                              />
                            </div>
                          ))}
                        </div>
                      ) : (
                        <ChartRenderer chartType={chartType} series={series} meta={meta} />
                      )}
                    </div>

                    <div className="summary-row">
                      {chartSummary && (
                        <div className="chart-summary glass">
                          <strong>AI summary:</strong> {chartSummary}
                        </div>
                      )}
                      <div className="export-actions">
                        <button className="btn ghost small" type="button" onClick={exportCSV}>Export CSV</button>
                        <button className="btn ghost small" type="button" onClick={exportPNG}>Export PNG</button>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="empty">Ask a question.</div>
                )}
              </div>
            </div>
          </section>
        </main>
      )}

      {/* Bottom composer */}
      {active && (
        <form className="composer glass" onSubmit={onSubmit}>
          <input
            ref={composerInputRef}
            id="composer-input"
            className="prompt-input big"
            placeholder="Ask another question…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Ask Sabermetric AI"
          />
          <button className="btn primary" type="submit" disabled={loading}>
            {loading ? "Analyzing…" : "Ask AI"}
          </button>
        </form>
      )}
    </div>
  );
}
