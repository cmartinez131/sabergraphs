import React from "react";
import { Link, useNavigate } from "react-router-dom";
import "../App.css";

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
            <header className="nav glass">
                <div className="brand">
                    <button
                        className="brand-home"
                        onClick={() => navigate("/")}
                        title="Back to Sabermetric AI"
                    >
                        <div className="logo">⚾︎</div>
                        <span className="brand-title">Sabermetric ai</span>
                    </button>
                </div>
                <div className="nav-actions">
                    <Link className="btn ghost small" to="/">Home</Link>
                    <button className="btn light small" type="button">Log in</button>
                    <button className="btn primary small" type="button">Sign up for free</button>
                </div>
            </header>

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
                        Sabermetric AI brings baseball questions straight to charts and answers with as little clicking as possible.
                        Using the OpenAI API, natural language prompts route to Python tools that query the database and return clean visuals fast.
                        It supports comparisons, advanced metrics, distributions, and projections, and charts adapt to the question.
                        This is a work in progress with pitcher data, live pitch feeds, postseason coverage, and broader query support on the way.
                    </p>

                    <h3>Project Overview</h3>
                    <p>
                        The full flow is simple and robust. Frontend calls the backend endpoint, the toolkit
                        hits the database, the toolkit shapes a clean series, the backend returns a canonical
                        payload, and the frontend renders with Nivo.
                    </p>
                    <pre style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
                        {`Frontend → Backend (endpoint) → Toolkit → DB → Toolkit shapes series → Backend returns canonical payload → Frontend renders Nivo`}
                    </pre>
                    <p>
                        Goal: an AI assisted baseball analytics app that turns natural language prompts into
                        interactive charts and projections.
                    </p>

                    <h3>Tech stack</h3>
                    <ul className="feature-list">
                        <li><b>Backend</b>: Python, FastAPI, SQLAlchemy</li>
                        <li><b>Frontend</b>: React, Nivo</li>
                        <li><b>Database</b>: PostgreSQL</li>
                        <li><b>AI</b>: OpenAI API for agentic orchestration with a rules based fallback</li>
                        <li><b>Python modules</b>: pandas, NumPy, scikit-learn</li>
                        <li><b>DevOps</b>: Docker and Docker Compose</li>
                    </ul>

                    <h3>Core user stories</h3>
                    <ul className="feature-list">
                        <li>Enter a query across seasons</li>
                        <li>Ask for stat distributions (e.g., histogram of HRs in 2023).</li>
                        <li>Compare two or more players on multiple stats.</li>
                        <li>View a player’s career arc or rolling averages.</li>
                        <li>See percentile ranks for a stat in a given year.</li>
                        <li>Run “what if” scenarios (e.g., increase BB% by 5%).</li>
                        <li>Ask for leaders, trends, and comparisons across seasons.</li>
                        <li>Project future performance like OPS, HR, wOBA, and more.</li>
                        <li>Export charts and data from the UI as PNG or CSV.</li>
                    </ul>

                    <h3>What's implemented</h3>
                    <ul className="feature-list">
                        <li>
                            <b>Canonical payload</b>: <code>{`{ chart_type, series, narration, meta? }`}</code> from the backend, rendered directly by the frontend.
                        </li>
                        <li>
                            <b>Analytics</b>: compare, leaderboards, career arcs, rolling means, year over year deltas, percentiles, improvement, rate per PA, radar multi-stat, histogram, multi-stat compare.
                        </li>
                        <li>
                            <b>Projections</b>: trailing-years baseline plus aging + KNN comparables with p10 to p90 bands.
                        </li>
                        <li>
                            <b>Agent route</b>: <code>/api/prompt</code> maps free text to tools and args using OpenAI with a rules fallback.
                        </li>
                    </ul>

                    <h3>API surface (snapshot)</h3>
                    <ul className="feature-list">
                        <li>
                            <b>Compare</b>: <code>POST /api/compare</code> (bar by year or line over range), <code>POST /api/compare_multi</code> (multi-stat grouped or stacked, or per-stat facets).
                        </li>
                        <li>
                            <b>Leaderboards</b>: <code>POST /api/leaderboard</code>, <code>/leaderboard_range</code>, <code>/leaderboard_by_year</code>.
                        </li>
                        <li>
                            <b>Time series</b>: <code>POST /api/career_arc</code>, <code>/rolling_mean</code>, <code>/yoy_change</code>.
                        </li>
                        <li>
                            <b>Distributions & ranks</b>: <code>POST /api/histogram</code>, <code>/percentile</code>, <code>/rate_per_pa</code>, <code>/radar</code>.
                        </li>
                        <li>
                            <b>Projections</b>: <code>POST /api/predict</code> (baseline and aging_knn; ML stubs).
                        </li>
                        <li>
                            <b>Agent</b>: <code>POST /api/prompt</code> (free-text interface).
                        </li>
                    </ul>


                    <h3>Data model</h3>
                    <ul className="feature-list">
                        <li>
                            <b>Table</b>: <code>batting_stats</code> loaded from 2015 to 2025 CSV into Postgres.
                        </li>
                        <li>
                            <b>Key</b>: composite <code>(player_id, year)</code>. Includes <code>full_name</code>, <code>plate_appearances</code>, standard batting stats, plus extra CSV columns reflected safely.
                        </li>
                        <li>
                            <b>Naming</b>: snake case stat names like <code>home_run</code>, <code>woba</code>, <code>on_base_plus_slg</code>.
                        </li>
                    </ul>

                    <h3>Roadmap</h3>
                    <ul className="feature-list">
                        <li>
                            <b>Phase 1 – Foundation</b>: Load data into Postgres, build the FastAPI toolkit, add AI + rules fallback.
                        </li>
                        <li>
                            <b>Phase 2 – App & Charts</b>: React UI, dynamic chart renderer, polished narration and error states.
                        </li>
                        <li>
                            <b>Phase 3 – What-If Engine</b>: Add sliders to tweak stats (BB%, K%, ISO), run quick projections, show Baseline vs Scenario on the chart, and include simple uncertainty bands (likely range).
                        </li>
                    </ul>


                    <h3>What If engine plan</h3>
                    <ul className="feature-list">
                        <li>
                            Parametric projection model that exposes inputs like K percent, BB percent, ISO.
                        </li>
                        <li>
                            Scenario parser maps phrases like improves plate discipline to BB percent and K percent deltas.
                        </li>
                        <li>
                            Return Baseline and Scenario series with narration that explains the difference.
                        </li>
                    </ul>

                    <h3>Next steps</h3>
                    <ul className="feature-list">
                        <li>Wire what if sliders to the agent and simulation engine.</li>
                        <li>Saved dashboards and shareable links.</li>
                        <li>Glossary and stat coverage expansion for pitching and defense.</li>
                        <li>Implement user login with secure authentication and session management.</li>
                        <li>Create a sign up page with form validation, password strength checks, and email verification.</li>
                    </ul>
                </section>
            </main>
        </div>
    );
}
