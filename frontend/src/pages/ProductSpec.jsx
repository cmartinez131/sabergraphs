// frontend/src/pages/ProductSpec.jsx
import React from "react";
import { Link, useNavigate } from "react-router-dom";
import "../App.css";
import NavBar from "../components/layout/NavBar";

function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
}

export default function ProductSpec() {
  const navigate = useNavigate();

  return (
    <div className="pricing-page">
      {/* Background */}
      <div className="bg">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="grain" />
      </div>

      {/* Minimal nav */}
      <NavBar onToggleTheme={toggleTheme} />

      <main className="container pricing">
        {/* Hero */}
        <section className="pricing-hero">
          <h1>Product Spec</h1>
          <p className="muted">Architecture, data sources, and roadmap for Sabermetric AI.</p>
        </section>

        {/* Content */}
        <section className="glass" style={{ padding: 16 }}>
          <h3>Why Sabermetric AI</h3>
          <p>
            Sabermetric AI lets you ask baseball questions in plain English and get a chart and a short answer back.
            No manual filters or dealing with finicky dashboards — just type what you want and see results.
            It already handles comparisons, career trends, percentiles, and simple projections. As of now, only yearly batter data is supported.
            Pitching, defense, and live feeds are on the way.
          </p>

          <h3>Project Overview</h3>
          <p>
            One request in, one clear response out. The frontend sends your prompt to the backend,
            the agent decides what tool to run, the toolkit queries Postgres, and the result comes back
            as a standard shape the UI can render into a chart. The frontend then provides options for 
            exporting the chart as PNG or CSV.
          </p>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
{`Frontend (Home.jsx) → /api/prompt → Agent (choose tool + args) → Toolkit → DB
→ Toolkit returns { chart_type, series, narration, meta } (single or facet)
→ Frontend applies label_map, renders with Nivo, and enables CSV/PNG export`}
          </pre>
          <p>
            Goal: a fast, friendly way to explore baseball data without learning a new UI.
          </p>

          <h3>Tech stack</h3>
          <ul className="feature-list">
            <li><b>Backend</b>: Python, FastAPI, SQLAlchemy</li>
            <li><b>Frontend</b>: React, Nivo</li>
            <li><b>Database</b>: PostgreSQL</li>
            <li><b>AI</b>: OpenAI API with a simple rules fallback</li>
            <li><b>Python</b>: pandas, NumPy, scikit-learn</li>
            <li><b>Dev</b>: Docker + Docker Compose</li>
          </ul>

          <h3>Deployment & Infra</h3>
          <ul className="feature-list">
            <li><b>Frontend</b>: Vercel</li>
            <li><b>Backend</b>: Render</li>
            <li><b>Database</b>: Neon (serverless Postgres)</li>
            <li><b>Config</b>: <code>REACT_APP_API_URL</code>, <code>DATABASE_URL</code>, <code>OPENAI_API_KEY</code>, CORS origin</li>
            <li><b>CI</b>: build/deploy from Vercel + Render dashboards</li>
          </ul>

          <h3>Core Features</h3>
          <ul className="feature-list">
            <li>Ask questions across one or more seasons</li>
            <li>Compare players on one or many stats</li>
            <li>See career arcs and rolling averages</li>
            <li>View percentile ranks by season</li>
            <li>Run simple what-if scenarios (e.g., adjust BB% or K%)</li>
            <li>Find leaders and trends across years</li>
            <li>Project basic future performance (OPS, HR, wOBA, etc.)</li>
            <li>Export any chart or data as PNG or CSV</li>
          </ul>

          <h3>What's implemented</h3>
          <ul className="feature-list">
            <li><b>Canonical payload</b>: <code>{`{ chart_type, series, narration, meta? }`}</code> for a single chart or a facet grid</li>
            <li><b>Analytics</b>: compare, leaderboards, career arcs, rolling mean, YoY change, percentiles, improvement, rate per PA, radar, multi-stat compare</li>
            <li><b>Projections</b>: trailing-years baseline + aging with KNN comps (p10–p90 bands)</li>
            <li><b>Agent</b>: <code>/api/prompt</code> turns free text into toolkit calls</li>
          </ul>

          <h3>API surface (snapshot)</h3>
          <ul className="feature-list">
            <li><b>Compare</b>: <code>POST /api/compare</code> (bar by year or line over range), <code>POST /api/compare_multi</code> (grouped/stacked or per-stat facets)</li>
            <li><b>Leaderboards</b>: <code>POST /api/leaderboard</code>, <code>/leaderboard_range</code>, <code>/leaderboard_by_year</code></li>
            <li><b>Time series</b>: <code>POST /api/career_arc</code>, <code>/rolling_mean</code>, <code>/yoy_change</code></li>
            <li><b>Ranks & rates</b>: <code>POST /api/percentile</code>, <code>/rate_per_pa</code>, <code>/radar</code></li>
            <li><b>Projections</b>: <code>POST /api/predict</code> (baseline + aging_knn)</li>
            <li><b>Agent</b>: <code>POST /api/prompt</code> (free-text entry point)</li>
          </ul>

          <h3>Agent & Prompts</h3>
          <p>
            The agent cleans up what you typed, recognizes stat names and aliases,
            pulls out players and years, picks the right tool, and returns a
            standard response the UI can draw.
          </p>
          <ul className="feature-list">
            <li><b>Aliases</b>: <code>1B/2B/3B</code> ↔ single/double/triple, <code>SO/K</code> ↔ strikeouts, <code>BB</code> ↔ walks, <code>OPS</code> ↔ <code>on_base_plus_slg</code></li>
            <li><b>Output</b>: <code>chart_type</code> (bar/line/radar/facet), <code>series</code> (Nivo-ready), <code>narration</code> (one-two lines), <code>meta</code> (labels, title, y-axis)</li>
          </ul>

          <h3>Data model</h3>
          <ul className="feature-list">
            <li><b>Table</b>: <code>batting_stats</code> from 2015–2025 CSVs</li>
            <li><b>Key</b>: <code>(player_id, year)</code>, plus <code>full_name</code>, <code>plate_appearances</code>, and common batting stats</li>
            <li><b>Naming</b>: snake_case like <code>home_run</code>, <code>woba</code>, <code>on_base_plus_slg</code></li>
          </ul>

          <h3>Roadmap</h3>
          <ul className="feature-list">
            <li><b>Phase 1: Foundation</b> Import data, build toolkit, add agent + rules fallback</li>
            <li><b>Phase 2: App & Charts</b> Refine UI, improve narration, better empty/error states</li>
            <li><b>Phase 3: What-If</b> Sliders for BB%/K%/ISO, quick projections, baseline vs scenario, simple bands</li>
          </ul>

          <h3>Next steps</h3>
          <ul className="feature-list">
            <li>Broaden stat coverage and add pitching/defense</li>
            <li>Add more prediction methods and tuning</li>
            <li>Hook up what-if sliders to the agent and sim logic</li>
            <li>Saved dashboards and shareable links</li>
            <li>Auth: signup, login, sessions</li>
            <li>Glossary for common stats and aliases</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
