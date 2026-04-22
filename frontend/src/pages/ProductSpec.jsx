import React from "react";
import "../App.css";
import NavBar from "../components/layout/NavBar";

function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
}

export default function ProductSpec() {
  return (
    <div className="pricing-page">
      <div className="bg">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="grain" />
      </div>

      <NavBar onToggleTheme={toggleTheme} />

      <main className="container pricing">
        <section className="pricing-hero">
          <h1>How It Works</h1>
        </section>

        <section className="glass" style={{ padding: 16 }}>
          <h3>Overview</h3>
          <p>
            Type a baseball question, get a chart back. The AI figures out what data you need, 
            queries the database, and returns a visualization. No filters or dashboards to learn.
          </p>

          <h3>Architecture</h3>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
{`Prompt → Agent (Claude) → Query Postgres → Return chart data → Render with Nivo
            ↓
  Two paths: NL→SQL (direct SQL generation)
         or Classic (tool-picker → analytics function)`}
          </pre>

          <h3>Stack</h3>
          <ul className="feature-list">
            <li><b>Frontend</b>: React, Nivo (charts), Vercel</li>
            <li><b>Backend</b>: FastAPI, SQLAlchemy, Render</li>
            <li><b>Database</b>: PostgreSQL (Neon)</li>
            <li><b>AI</b>: Anthropic Claude API</li>
          </ul>

          <h3>What You Can Ask</h3>
          <ul className="feature-list">
            <li>Compare players across stats and seasons</li>
            <li>Career trends and rolling averages</li>
            <li>Leaderboards and percentile ranks</li>
            <li>Simple projections with confidence bands</li>
            <li>Export any result as PNG or CSV</li>
          </ul>

          <h3>Current Scope</h3>
          <p>
            Batting stats from 2015—2025. Pitching, defense, and live data coming soon.
          </p>

          <h3>Roadmap</h3>
          <ul className="feature-list">
            <li>Pitching and defensive stats</li>
            <li>What-if sliders (adjust K%, BB%, etc.)</li>
            <li>Saved queries and shareable links</li>
            <li>User accounts</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
