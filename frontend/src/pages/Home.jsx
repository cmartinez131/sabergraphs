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

  // Clarification round-trip ({ text, questions }) + per-question selections
  const [clarify, setClarify] = useState(null);
  const [clarifySel, setClarifySel] = useState({});

  // Server-backed conversations list
  const [conversations, setConversations] = useState([]);

  const heroInputRef = useRef(null);
  const composerInputRef = useRef(null);
  const chartNodeRef = useRef(null);
  const navigate = useNavigate();

  const active = loading || hasChart || !!clarify;
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

  // Three curated examples per category: one classic, one that shows off a
  // newer surface (pitching, rookie alignment, bat tracking), one range.
  const promptGroups = useMemo(
    () => ({
      "Player comparisons": [
        "Judge vs Soto home runs in 2025",
        "Compare Volpe and Judge home runs in their rookie seasons",
        "Skubal vs Skenes ERA in 2025",
      ],
      "Stat leaderboards and rankings": [
        "Top 5 players in home runs in 2025",
        "Lowest ERA in 2024, minimum 150 innings",
        "Fastest average bat speed in 2025, minimum 100 competitive swings",
      ],
      "Player trends": [
        "Mookie Betts batting average from 2016 to 2025",
        "Kershaw ERA by season from 2015 to 2025",
        "Judge whiff % from 2018 to 2025",
      ],
      "Future stat projections": [
        "Forecast Aaron Judge OPS for the next 6 years",
        "Estimate Shohei Ohtani HR for the next 3 years",
        "Project Elly De La Cruz stolen bases over the next 4 years",
      ],
      "Single stat lookups": [
        "Shohei Ohtani OPS in 2024",
        "Paul Skenes ERA in 2024",
        "Soto steals in 2025",
      ],
    }),
    []
  );

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
      } catch { }
    }, 800);
  }

  async function callPrompt(text, hints = null) {
    setLoading(true);
    setHasChart(false);
    setChartSummary("");
    setFacets(null);
    setMeta({});
    setClarify(null);
    setClarifySel({});
    try {
      const res = await apiPrompt(text, { hints });

      // The backend needs the user to disambiguate (which player / which
      // stats) before it can chart, so render clickable options instead.
      // Recommended options (e.g. Home Runs / ERA) arrive pre-selected so
      // "Generate chart" is one click away.
      if (res.chart_type === "clarify") {
        const questions = res.clarification || [];
        const preSel = {};
        questions.forEach((q, i) => {
          if (q.multi) {
            const rec = (q.options || [])
              .filter((o) => o.recommended)
              .map((o) => o.value);
            if (rec.length) preSel[i] = rec;
          }
        });
        setClarify({ text, questions });
        setClarifySel(preSel);
        setChartSummary(res.narration || "");
        return;
      }

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
    setClarify(null);
    setClarifySel({});
    navigate("/");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------- Clarification round-trip ---------- */

  function toggleClarifyOption(qIdx, option, multi) {
    setClarifySel((prev) => {
      const cur = prev[qIdx] || [];
      let next;
      if (multi) {
        const has = cur.some((v) => JSON.stringify(v) === JSON.stringify(option.value));
        next = has
          ? cur.filter((v) => JSON.stringify(v) !== JSON.stringify(option.value))
          : [...cur, option.value];
      } else {
        next = [option.value];
      }
      return { ...prev, [qIdx]: next };
    });
  }

  function clarifyAnswered(sel) {
    if (!clarify) return false;
    return clarify.questions.every((_, i) => (sel[i] || []).length > 0);
  }

  function submitClarify(selOverride = null) {
    if (!clarify) return;
    const sel = selOverride || clarifySel;
    const players = [];
    const stats = [];
    clarify.questions.forEach((q, i) => {
      (sel[i] || []).forEach((v) => {
        if (q.kind === "stat" && v.stat) stats.push(v.stat);
        else if (q.kind === "player") players.push(v);
      });
    });
    callPrompt(clarify.text, {
      players,
      ...(stats.length ? { stats } : {}),
    });
  }

  function pickClarifyOption(qIdx, q, option) {
    if (q.multi) {
      toggleClarifyOption(qIdx, option, true);
      return;
    }
    // Single-select: record the choice. Auto-submit ONLY when the whole
    // card is single-select confirms (a lone "Did you mean X?" resolves in
    // one click). If any multi-select question is on the card, the
    // "Generate chart" button is the one and only trigger; clicking a
    // player name must never fire the query out from under the user.
    const sel = { ...clarifySel, [qIdx]: [option.value] };
    setClarifySel(sel);
    const buttonDriven = clarify.questions.some((qq) => qq.multi);
    if (
      !buttonDriven &&
      clarify.questions.every((_, i) => (sel[i] || []).length > 0)
    ) {
      submitClarify(sel);
    }
  }

  function groupClarifyOptions(options) {
    const groups = [];
    (options || []).forEach((o, oIdx) => {
      const g = o.group || "";
      let bucket = groups.find((x) => x.g === g);
      if (!bucket) {
        bucket = { g, items: [] };
        groups.push(bucket);
      }
      bucket.items.push({ o, oIdx });
    });
    return groups;
  }

  function isClarifySelected(qIdx, option) {
    return (clarifySel[qIdx] || []).some(
      (v) => JSON.stringify(v) === JSON.stringify(option.value)
    );
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
            .catch(() => { });
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
              <span className="accent">See data and get insights.</span>
            </h1>
            {/* <p className="sub">Natural language → analytics, projections, and beautiful charts.</p> */}

            <div className="status-row">
              <div className="status-card glass getting-started">
                <div className="gs-head">
                  <h2>Getting started</h2>
                </div>

                <div className="gs-steps">
                  <div className="step">
                    <div className="step-icon">🔎</div>
                    <div className="step-body">
                      <div className="step-title">Ask</div>
                      <div className="step-copy">Type a baseball question.</div>
                    </div>
                  </div>

                  <div className="step">
                    <div className="step-icon">📈</div>
                    <div className="step-body">
                      <div className="step-title">Explore</div>
                      <div className="step-copy">Fetch data and render the right chart automatically.</div>
                    </div>
                  </div>

                  <div className="step">
                    <div className="step-icon">⬇️</div>
                    <div className="step-body">
                      <div className="step-title">Export</div>
                      <div className="step-copy">Download the chart as PNG or the data as CSV.</div>
                    </div>
                  </div>
                </div>
                <div className="gs-foot muted">
                  <div>
                    <b>Batter stats:</b> AVG, HR, OPS, wOBA, SLG, OBP, RBI, SB,
                    K%, BB%, barrel %, exit velocity, sprint speed, bat speed
                    (2024+), and more.
                  </div>
                  <div>
                    <b>Pitcher stats:</b> ERA, wins, saves, strikeouts, innings
                    pitched, quality starts, opponent AVG, fastball velocity,
                    and more.
                  </div>
                  <div className="gs-soon">Coming soon: pitch level stats.</div>
                </div>
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
                  <p className="muted status-footnote">
                    *Batter and pitcher data, 2015-2025 seasons
                  </p>
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

            <h2 className="chips-heading">Try asking</h2>
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
                ) : clarify ? (
                  <div className="clarify-card">
                    <div className="clarify-heading">
                      {chartSummary || "Quick check before I chart this…"}
                    </div>
                    {clarify.questions.map((q, qIdx) => (
                      <div key={qIdx} className="clarify-question">
                        <div className="clarify-prompt">{q.prompt}</div>
                        {groupClarifyOptions(q.options).map(({ g, items }) => (
                          <div key={g || "all"} className="chip-subgroup">
                            {g && <div className="chip-group-label">{g}</div>}
                            <div className="chips">
                              {items.map(({ o, oIdx }) => (
                                <button
                                  key={oIdx}
                                  type="button"
                                  className={
                                    "chip" +
                                    (isClarifySelected(qIdx, o) ? " selected" : "")
                                  }
                                  onClick={() => pickClarifyOption(qIdx, q, o)}
                                >
                                  <span className="chip-label">{o.label}</span>
                                  {o.description && (
                                    <span className="chip-desc"> · {o.description}</span>
                                  )}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                    {clarify.questions.some((q) => q.multi) && (
                      <div className="clarify-actions">
                        <button
                          type="button"
                          className="btn primary"
                          disabled={!clarifyAnswered(clarifySel)}
                          onClick={() => submitClarify()}
                        >
                          Generate chart
                        </button>
                        {!clarifyAnswered(clarifySel) && (
                          <span className="clarify-hint">
                            Pick an option for each question above to continue.
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ) : hasChart &&
                  !facets &&
                  (series || []).length > 0 &&
                  (series || []).every(
                    (s) => Array.isArray(s?.data) && s.data.length === 0
                  ) ? (
                  // Nothing plottable (e.g. every named player was censored
                  // or has no data): show the explanation, not empty axes.
                  <div className="clarify-card">
                    <div className="clarify-heading">Nothing to chart for this one</div>
                    <div className="clarify-prompt">
                      {chartSummary || "No data matched this question."}
                    </div>
                  </div>
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
