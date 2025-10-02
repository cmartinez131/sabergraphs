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
          <h1>Pricing (Work in Progress)</h1>
          <p className="muted">Start free. Upgrade for projections, faster speed, and what-if analytics.</p>

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
          {/* Free (logged-in) */}
          <article className="plan-card glass">
            <div className="plan-header">
              <h3>Free</h3>
              <p className="plan-tag">Try it out</p>
              <div className="plan-price">
                <span className="price">$0</span>
                <span className="per">/ month</span>
              </div>
            </div>
            <ul className="feature-list">
              <li>✓ Logged-in access</li>
              <li>✓ Player & team comparisons</li>
              <li>✓ Clean charts (watermarked exports)</li>
              <li>✓ 15 AI queries/day</li>
              <li>✓ Local chat history</li>
            </ul>
            <button className="btn primary wide">Get Free</button>
          </article>

          {/* Plus */}
          <article className="plan-card glass popular">
            <div className="plan-header">
              <h3>Plus</h3>
              <p className="plan-tag">Fans & creators</p>
              <div className="plan-price">
                <span className="price">{annual ? plus.perMonth : fmtMo(PLUS_MO)}</span>
                <span className="per">{annual ? "billed annually" : "/ month"}</span>
              </div>
              {annual && <div className="badge">{plus.billedText}</div>}
            </div>
            <ul className="feature-list">
              <li>✓ Everything in Free</li>
              <li>✓ Projections & playoff sims</li>
              <li>✓ Save/share dashboards</li>
              <li>✓ CSV/PNG exports (no watermark)</li>
              <li>✓ AI chart summaries</li>
              <li>✓ Priority speed • ~200–400 queries/mo*</li>
            </ul>
            <button className="btn primary wide">Get Plus</button>
            <p className="tiny muted">*Fair-use policy with gentle rate limits.</p>
          </article>

          {/* Pro */}
          <article className="plan-card glass">
            <div className="plan-header">
              <h3>Pro</h3>
              <p className="plan-tag">Analysts & power users</p>
              <div className="plan-price">
                <span className="price">{annual ? pro.perMonth : fmtMo(PRO_MO)}</span>
                <span className="per">{annual ? "billed annually" : "/ month"}</span>
              </div>
              {annual && <div className="badge">{pro.billedText}</div>}
            </div>
            <ul className="feature-list">
              <li>✓ Everything in Plus</li>
              <li>✓ What-if scenarios (natural-language or sliders)</li>
              <li>✓ Bulk comparisons & batch exports</li>
              <li>✓ Player/team alerts</li>
              <li>✓ API preview tokens</li>
              <li>✓ Fastest speed • higher limits</li>
            </ul>
            <button className="btn primary wide">Get Pro</button>
          </article>
        </section>

        {/* Compare table (kept compact) */}
        <section className="compare glass">
          <h4>Compare features</h4>
          <div className="compare-grid">
            <span></span><span>Free</span><span>Plus</span><span>Pro</span>

            <span>AI queries</span><span>15/day</span><span>~200–400/mo*</span><span>Soft-unlimited*</span>
            <span>Projections & sims</span><span>—</span><span>✓</span><span>✓</span>
            <span>What-if scenarios</span><span>—</span><span>Basic (roadmap)</span><span>Advanced</span>
            <span>Save/share dashboards</span><span>—</span><span>✓</span><span>✓</span>
            <span>Exports</span><span>Watermark</span><span>CSV/PNG</span><span>Batch CSV/PNG</span>
            <span>Speed</span><span>Queued</span><span>Priority</span><span>Fastest</span>
            <span>Alerts</span><span>—</span><span>—</span><span>✓</span>
            <span>API access</span><span>—</span><span>—</span><span>Preview</span>
          </div>
          <p className="tiny muted">*Fair-use limits and abuse guardrails apply.</p>
        </section>
      </main>
    </div>
  );
}
