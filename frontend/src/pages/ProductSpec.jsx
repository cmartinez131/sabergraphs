import React from "react";
import "../App.css";
import NavBar from "../components/layout/NavBar";

export default function ProductSpec() {
  return (
    <div className="pricing-page">
      <div className="bg">
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="grain" />
      </div>

      <NavBar />

      <main className="container pricing">
        <section className="pricing-hero">
          <h1>How It Works</h1>
        </section>

        <section className="glass" style={{ padding: 16 }}>
          <h3>Overview</h3>
          <p>
            Type a baseball question, get a chart back. The app figures out
            which players and stats you mean, asking you to confirm when a
            name is ambiguous, then either writes a SQL query or runs
            built-in analytics like projections and rookie season
            comparisons. Results come from a database of batting, pitching,
            and Statcast bat tracking stats, and every answer arrives as a
            chart with a plain English summary.
          </p>

          <h3>How a Question Becomes a Chart</h3>
          <div className="arch-diagram">
            <div className="arch-flow">
              <div className="arch-node">
                <span className="arch-step">1</span>
                <b>You ask a question</b>
                <span>typed in plain English</span>
              </div>
              <div className="arch-node">
                <span className="arch-step">2</span>
                <b>Players and stats identified</b>
                <span>the app confirms if unclear</span>
              </div>
              <div className="arch-node">
                <span className="arch-step">3</span>
                <b>The right tool chosen</b>
                <span>SQL query or built-in analytics</span>
              </div>
              <div className="arch-node">
                <span className="arch-step">4</span>
                <b>Every query safety checked</b>
                <span>validated and run read-only</span>
              </div>
              <div className="arch-node">
                <span className="arch-step">5</span>
                <b>The database answers</b>
                <span>batting, pitching, Statcast</span>
              </div>
              <div className="arch-node">
                <span className="arch-step">6</span>
                <b>You get a chart</b>
                <span>summary included, PNG and CSV export</span>
              </div>
            </div>
          </div>

          <h3>Technical Stack</h3>
          <ul className="feature-list">
            <li><b>Frontend</b>: JavaScript, React, Nivo charts, deployed on Vercel</li>
            <li><b>Backend</b>: Python, FastAPI, SQLAlchemy, deployed on Render</li>
            <li><b>Database</b>: PostgreSQL</li>
            <li><b>Data and ML</b>: SQL, pandas, NumPy, scikit-learn, Claude API</li>
            <li><b>Infrastructure</b>: Docker</li>
          </ul>

          <h3>What You Can Ask</h3>
          <ul className="feature-list">
            <li>Compare players across stats and seasons, batters and pitchers</li>
            <li>Rookie season and career-aligned comparisons</li>
            <li>Career trends and rolling averages</li>
            <li>Leaderboards with qualifiers (min PA, min innings, min swings)</li>
            <li>Projections with honest, backtested uncertainty</li>
            <li>Export any result as PNG or CSV</li>
          </ul>

          <h3>Current Scope</h3>
          <p>
            Batting and pitching stats from 2015 to 2025, plus Statcast bat
            tracking from the 2024 and 2025 seasons. All charted data lives
            in the app's own PostgreSQL database; the MLB Stats API is used
            only to identify players when a name is ambiguous.
          </p>

          <h3>Future Roadmap</h3>
          <ul className="feature-list">
            <li>Pitch level stats</li>
            <li>Defensive stats</li>
            <li>What-if sliders (adjust K%, BB%, etc.)</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
