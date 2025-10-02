import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import "../App.css";

export default function Pricing() {
  const navigate = useNavigate();
  const [annual, setAnnual] = useState(true);

  // ----- Pricing helpers -----
  const fmtMo = (n) => `$${n}/mo`;
  const annualize = (mo, savePct) => {
    const billed = Math.round((mo * 12 * (100 - savePct)) / 100);
    return {
      perMonth: `$${Math.round(billed / 12)}/mo`,
      billedText: `Pay $${billed}/yr — save ${savePct}%`,
    };
  };

  // Price points
  const PLUS_MO = 9;   // $9 monthly → $84/yr (~$7/mo) with 22% off
  const PRO_MO = 29;  // $29 monthly → $264/yr (~$22/mo) with 24% off

  const plus = annual ? annualize(PLUS_MO, 22) : { perMonth: fmtMo(PLUS_MO) };
  const pro = annual ? annualize(PRO_MO, 24) : { perMonth: fmtMo(PRO_MO) };

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
          <h1>Pricing Plans</h1>
          <p className="muted">Start free. Upgrade for projections, conversational AI, and what-if analytics.</p>

          <div className="price-toggle glass" role="tablist" aria-label="Billing period">
            <button
              className={`toggle-btn ${!annual ? "active" : ""}`}
              onClick={() => setAnnual(false)}
              type="button"
              role="tab"
              aria-selected={!annual}
            >
              Monthly
            </button>
            <button
              className={`toggle-btn ${annual ? "active" : ""}`}
              onClick={() => setAnnual(true)}
              type="button"
              role="tab"
              aria-selected={annual}
            >
              Annual <span className="save-badge">Save</span>
            </button>
          </div>
        </section>

        {/* Plans */}
        <section className="plan-grid">
          {/* Free */}
          <article className="plan-card glass">
            <div className="plan-header">
              <h3>Free</h3>
              <p className="plan-tag">For casual fans</p>
              <div className="plan-price">
                <span className="price">$0</span>
                <span className="per">/ month</span>
              </div>
            </div>
            <ul className="feature-list">
              <li>✓ Basic player & team comparisons</li>
              <li>✓ Watermarked chart exports</li>
              <li>✓ 20 AI queries/month</li>
              <li>✓ Local chat history</li>
              <li>— Conversational Memory</li>
              <li>— Projections & Sims</li>
            </ul>
            <button className="btn primary wide">Get Started</button>
          </article>

          {/* Plus */}
          <article className="plan-card glass popular">
            <div className="plan-header">
              <h3>Plus</h3>
              <p className="plan-tag">For fans & creators</p>
              <div className="plan-price">
                <span className="price">{annual ? plus.perMonth : fmtMo(PLUS_MO)}</span>
                <span className="per">{annual ? "billed annually" : "/ month"}</span>
              </div>
              {annual && <div className="badge">{plus.billedText}</div>}
            </div>
            <ul className="feature-list">
              <li>✓ Everything in Free, plus:</li>
              <li>✓ Baseline Projections & Playoff Sims</li>
              <li>✓ Conversational Memory (AI remembers context)</li>
              <li>✓ Save & share dashboards</li>
              <li>✓ No-watermark CSV/PNG exports</li>
              <li>✓ AI-generated chart summaries</li>
              <li>✓ Priority speed • Up to 500 AI credits/mo*</li>
            </ul>
            <button className="btn primary wide">Start Plus Trial</button>
            <p className="tiny muted">*Credits used for queries & projections.</p>
          </article>

          {/* Pro */}
          <article className="plan-card glass">
            <div className="plan-header">
              <h3>Pro</h3>
              <p className="plan-tag">For analysts & power users</p>
              <div className="plan-price">
                <span className="price">{annual ? pro.perMonth : fmtMo(PRO_MO)}</span>
                <span className="per">{annual ? "billed annually" : "/ month"}</span>
              </div>
              {annual && <div className="badge">{pro.billedText}</div>}
            </div>
            <ul className="feature-list">
              <li>✓ Everything in Plus, plus:</li>
              <li>✓ Advanced 'What-if' Scenario Engine</li>
              <li>✓ Access to Advanced Projection Models</li>
              <li>✓ Bulk Comparisons & Batch Exports</li>
              <li>✓ Player & Team Performance Alerts</li>
              <li>✓ Standard API Access (Rate-limited)</li>
              <li>✓ Fastest speed • Up to 2000 AI credits/mo*</li>
            </ul>
            <button className="btn primary wide">Go Pro</button>
            <p className="tiny muted">*Credits used for all features.</p>
          </article>
        </section>

        {/* Compare table (kept compact) */}
        <section className="compare glass">
          <h4>Compare Features</h4>
          <div className="compare-grid">
            <span></span><span>Free</span><span>Plus</span><span>Pro</span>

            <span>AI Queries/Credits</span><span>20/mo</span><span>~500 credits/mo*</span><span>~2000 credits/mo*</span>
            <span>Conversational AI</span><span>—</span><span>✓</span><span>✓</span>
            <span>Baseline Projections</span><span>—</span><span>✓</span><span>✓</span>
            <span>Advanced Models</span><span>—</span><span>—</span><span>✓</span>
            <span>What-if Scenarios</span><span>—</span><span>—</span><span>Advanced</span>
            <span>Save/Share Dashboards</span><span>—</span><span>✓</span><span>✓</span>
            <span>Exports</span><span>Watermark</span><span>CSV/PNG</span><span>Batch CSV/PNG</span>
            <span>Alerts</span><span>—</span><span>—</span><span>✓</span>
            <span>API Access</span><span>—</span><span>—</span><span>Standard</span>
            <span>Speed</span><span>Standard</span><span>Priority</span><span>Fastest</span>
          </div>
          <p className="tiny muted">*A fair-use policy applies. Simple queries use fewer credits than complex scenarios.</p>
        </section>
      </main>
    </div>
  );
}