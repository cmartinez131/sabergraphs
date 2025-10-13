// frontend/src/pages/Home.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toPng } from "html-to-image";

import {
  health as apiHealth,
  prompt as apiPrompt,
  historyLog,
  historyRecent,
  historyGet,
  historyDelete, // delete endpoint
} from "../hooks/api";

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

// ---- tiny util to show "2h", "3d", etc. for updated time ----
function timeAgoISO(iso) {
  try {
    const t = new Date(iso).getTime();
    const s = Math.floor((Date.now() - t) / 1000);
    if (s < 60) return "now";
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h`;
    const d = Math.floor(h / 24);
    return `${d}d`;
  } catch {
    return "";
  }
}

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
  const [chartSummary, setChartSummary] = useState("");

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "dark");

  // Server-backed conversations list
  const [conversations, setConversations] = useState([]);

  const heroInputRef = useRef(null);
  const composerInputRef = useRef(null);
  const chartNodeRef = useRef(null);
  const navigate = useNavigate();

  const active = loading || hasChart;
  const loggedIn = false; // wire to real auth later

  // ---------- Health check ----------
  useEffect(() => {
    let cancelled = false;
    apiHealth()
      .then((d) => {
        if (cancelled) return;
        const msg = d?.message || "";
        const ok = d?.status === "ok" || /running|ready|hello|ok/i.test(msg);
        setBackend({ ok, text: ok ? "Running" : msg || "Connecting..." });
      })
      .catch(() => {
        if (cancelled) return;
        setBackend({ ok: false, text: "Could not connect to backend." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ---------- Load recent conversations from server ----------
  async function loadRecent() {
    try {
      const list = await historyRecent(20);
      setConversations(
        (list || []).map((c) => ({
          id: c.id,
          title: c.title,
          updated: timeAgoISO(c.updated_at),
        }))
      );
    } catch {
      // Silent fail keeps UI usable even if history is down
    }
  }

  useEffect(() => {
    loadRecent();
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
        "Compare Acuña, Soto, and Betts on singles, doubles, triples, and HR in 2025",
        "Compare Carroll, Witt Jr., and Tatis Jr. sprint speed in 2024",
        "Compare Lindor and Marte on steals from 2020 to 2025",
        "Stanton and Soto slugging % from 2021 to 2025",
        "luisangel acuna and ronald acuna jr slugging % from 2022 to 2025",
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
        "Lowest 10 K% in 2023",
        "bottom 10 strikeout % in 2023",
        "leader in single season slugging percentage from 2020 to 2025",
        "top 12 stolen bases totals between 2024 and 2025",
        "top 8 OPS average from 2022 to 2024",
        "Top 5 Home Run leaders 2020–2025 (average per year)",
        "Home run leaders 2020–2025 (sum)"
      ],
      "Analyze player trends": [
        "Rendon batting average from 2015 to 2025",
        "strikeout percentage by season for giancarlo stanton 2019 - 2023",
        "Stanton slugging % from 2022 to 2025",
        "bregman home runs 2015 to 2025",
        "Judge whiff % 2018 to 2025",
        "Mookie Betts batting average from 2016 to 2025",
        "Kris Bryant batting average from 2016 to 2025",
      ],
      "Look up a single stat": [
        "Shohei Ohtani OPS in 2024",
        "Mookie Betts whiff percentage in 2020",
        "Soto Steals in 2025",
        "Most RBIs in 2019",
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
    setTimeout(async () => {
      const demoSeries = genLine();
      const payload = {
        chart_type: "line",
        series: demoSeries,
        meta: { title: "Demo line chart" },
        narration: "Quick take: the trend peaks mid-season before cooling off into September.",
      };

      setSeries(demoSeries);
      setChartType("line");
      setLoading(false);
      setHasChart(true);
      setChartSummary(payload.narration);
      window.scrollTo({ top: 0, behavior: "smooth" });

      // ALWAYS create a new conversation for the demo
      try {
        await historyLog({
          prompt: "demo",
          payload,
          title: "Demo line chart",
          conversation_id: null, // ← force new conversation
        });
        await loadRecent();
      } catch {}
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

      // ALWAYS create a new conversation for every prompt
      try {
        await historyLog({
          prompt: text,
          payload: res,
          title: incomingMeta.title || text.slice(0, 80),
          conversation_id: null, // ← force new conversation
        });
        await loadRecent();
      } catch {
        // history errors shouldn't block UX
      }
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
  // inside Home.jsx
async function exportPNG({ mode = "screen", size = 1200 } = {}) {
  if (!chartNodeRef.current) return;

  // Capture just the chart area (title + chart), or facet grid
  const selector = chartType === "facet" ? ".facet-grid" : ".chart-surface";
  const node = chartNodeRef.current.querySelector(selector) || chartNodeRef.current;

  const rect = node.getBoundingClientRect();
  let W = rect.width, H = rect.height;
  const style = {
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    margin: 0,
    padding: 0,
    transformOrigin: "top left",
  };

  if (mode === "square-stretch") {
    // Fill a square by stretching X and Y independently
    W = H = size;
    style.transform = `scale(${W / rect.width}, ${H / rect.height})`;
  } else if (mode === "square-pad") {
    // Keep aspect, center inside a square (letterbox)
    W = H = size;
    const s = Math.min(W / rect.width, H / rect.height);
    const offX = (W - rect.width * s) / 2;
    const offY = (H - rect.height * s) / 2;
    style.transform = `translate(${offX}px, ${offY}px) scale(${s})`;
  }

  try {
    const dataUrl = await toPng(node, {
      width: W,
      height: H,
      style,          
      backgroundColor: "#ffffff",
      cacheBust: true,
      pixelRatio: 2,
    });
    const base = sanitizeFileName(meta?.title || "sabermetric_ai_chart");
    downloadURL(dataUrl, `${base}.png`);
  } catch (e) {
    console.error("PNG export failed", e);
    alert("PNG export failed (see console).");
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
          // READ-ONLY VIEW: load and render the last entry but DO NOT set a conversation id.
          historyGet(c.id)
            .then((conv) => {
              const entries = conv?.entries || [];
              const last = entries[entries.length - 1];
              if (!last) return;
              const payload = last.payload || {};

              setChartSummary(payload.narration || "");
              setMeta(payload.meta || {});
              if (payload.facets) {
                setChartType("facet");
                setFacets(payload.facets);
                setSeries([]);
              } else {
                setChartType(payload.chart_type || "bar");
                setSeries(payload.series || []);
                setFacets(null);
              }
              setHasChart(true);
              setQuery(last.prompt || "");
              window.scrollTo({ top: 0, behavior: "smooth" });
            })
            .catch(() => {});
        }}
        onDeleteConversation={async (id) => {
          // Optimistic: remove immediately, then confirm with server
          setConversations((prev) => prev.filter((x) => x.id !== id));
          try {
            await historyDelete(id);
            await loadRecent();
          } catch {
            // If it fails, refresh from server to restore state
            await loadRecent();
          }
        }}
        loggedIn={loggedIn}
        onNewChat={resetUI}
      />

      {/* Navbar */}
      <NavBar
        onToggleTheme={toggleTheme}
        onOpenSidebar={() => { 
          setSidebarOpen(true); 
          loadRecent(); 
        }}
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
              <button className="btn primary" type="submit">Ask</button>
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
            {loading ? "Analyzing…" : "Ask"}
          </button>
        </form>
      )}
    </div>
  );
}
