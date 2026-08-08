# backend/app/toolkit/backtest_report.py
#
# Offline backtest report generator. Runs the season-holdout harness against
# the live database, prints the markdown report to STDOUT (all progress goes
# to STDERR) and writes the raw results JSON next to the trained models so
# /api/backtest can serve precomputed numbers.
#
# Usage (from the repo root on the host):
#   docker exec sabermetric_backend python -m app.toolkit.backtest_report > docs/BACKTEST.md
#
# Dev/smoke variant (small player subset, no KNN):
#   docker exec sabermetric_backend python -m app.toolkit.backtest_report \
#       --systems naive,trailing,marcel --player-limit 25 > /dev/null

import argparse
import json
import os
import sys
from datetime import date

from ..db.database import SessionLocal, engine
from .backtest import (
    DEFAULT_SYSTEMS,
    NOMINAL_BAND,
    RESULTS_JSON,
    SYSTEM_LABELS,
    run_season_holdout,
)
from .marcel import (
    AGE_DECLINE_PER_YEAR,
    AGE_IMPROVE_PER_YEAR,
    BALLAST_PA,
    PA_CONSTANT,
    PA_WEIGHTS,
    PEAK_AGE,
    stat_kind,
)

STAT_LABELS = {"woba": "wOBA", "home_run": "Home runs"}


def _fmt(stat, v):
    if v is None:
        return "—"
    return f"{v:.4f}" if stat_kind(stat) == "rate" else f"{v:.2f}"


def _rows_for(results, key, **filters):
    rows = results.get(key, [])
    for f, val in filters.items():
        rows = [r for r in rows if r.get(f) == val]
    return rows


def _season_table(results, stat, metric, seasons, systems):
    header = "| System | " + " | ".join(str(s) for s in seasons) + " | Overall |"
    sep = "|---" * (len(seasons) + 2) + "|"
    lines = [header, sep]
    for system in systems:
        cells = []
        for season in seasons:
            r = _rows_for(results, "per_season", system=system, stat=stat, season=season)
            cells.append(_fmt(stat, r[0][metric]) if r else "—")
        o = _rows_for(results, "overall", system=system, stat=stat)
        cells.append(_fmt(stat, o[0][metric]) if o else "—")
        lines.append(f"| {SYSTEM_LABELS.get(system, system)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _n_table(results, stat, seasons, systems):
    lines = ["| System | " + " | ".join(str(s) for s in seasons) + " |",
             "|---" * (len(seasons) + 1) + "|"]
    for system in systems:
        cells = []
        for season in seasons:
            r = _rows_for(results, "per_season", system=system, stat=stat, season=season)
            cells.append(str(r[0]["n"]) if r else "—")
        lines.append(f"| {SYSTEM_LABELS.get(system, system)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _bucket_table(results, stat, systems):
    buckets = []
    for r in _rows_for(results, "per_bucket", stat=stat):
        if r["bucket"] not in buckets:
            buckets.append(r["bucket"])
    buckets.sort()  # "2-3...", "rookie...", "veteran..." -> reorder below
    order = [b for b in buckets if b.startswith("rookie")] + \
            [b for b in buckets if b.startswith("2-3")] + \
            [b for b in buckets if b.startswith("veteran")]
    lines = ["| System | " + " | ".join(f"{b} — RMSE / MAE / n" for b in order) + " |",
             "|---" * (len(order) + 1) + "|"]
    for system in systems:
        cells = []
        for b in order:
            r = _rows_for(results, "per_bucket", system=system, stat=stat, bucket=b)
            if r:
                cells.append(f"{_fmt(stat, r[0]['rmse'])} / {_fmt(stat, r[0]['mae'])} / {r[0]['n']}")
            else:
                cells.append("—")
        lines.append(f"| {SYSTEM_LABELS.get(system, system)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _calibration_table(results, systems):
    lines = ["| System | Stat | Band | Empirical coverage | n |",
             "|---|---|---|---|---|"]
    for r in results.get("calibration", []):
        if r["system"] not in systems:
            continue
        lines.append(
            f"| {SYSTEM_LABELS.get(r['system'], r['system'])} | {STAT_LABELS.get(r['stat'], r['stat'])} "
            f"| out-of-sample residual p10–p90 | {100.0 * r['coverage']:.1f}% | {r['n_eval']} |"
        )
    for r in results.get("knn_native_band", []):
        lines.append(
            f"| KNN-aging | {STAT_LABELS.get(r['stat'], r['stat'])} "
            f"| model's own p10–p90 output | {100.0 * r['coverage']:.1f}% | {r['n_eval']} |"
        )
    return "\n".join(lines)


def build_markdown(results, seasons, systems, stats):
    cfg = results["config"]
    parts = [f"""# Backtest — Next-Season Forecast Systems

Generated {date.today().isoformat()} by `python -m app.toolkit.backtest_report`.
Numbers are reported exactly as measured; nothing is filtered or reframed.

## Design

Season-holdout evaluation: every system is trained only on seasons ≤ N−1 and
scored on season N, for N ∈ {{{", ".join(str(s) for s in seasons)}}}. The KNN-aging system runs with a
hard `max_year = N−1` cutoff threaded through all of its queries (league
curve, comparable selection, and the comparables' future paths), so no
system sees the evaluation period.

**Systems**

| System | Definition |
|---|---|
| Naive repeat | Repeat the player's most recent observed season |
| Trailing mean (3yr) | Unweighted mean of the last 3 observed seasons (the app's existing baseline) |
| KNN-aging | League aging-curve ratios blended with KNN-comparable ratio paths (the app's existing `aging_knn` method) |
| Marcel | 5/4/3 recency weighting, {BALLAST_PA:.0f} PA league-average ballast, age adjustment around {PEAK_AGE} (+{AGE_IMPROVE_PER_YEAR:.1%}/yr below, −{AGE_DECLINE_PER_YEAR:.1%}/yr above), projected PA = {PA_WEIGHTS[0]}·PA(t−1) + {PA_WEIGHTS[1]}·PA(t−2) + {PA_CONSTANT:.0f} |

**Eligibility (identical for all systems):** target-season PA ≥ {cfg["min_pa"]} with the
stat observed, plus at least one observed season in the {cfg["eligibility_window_years"]}-year window
before the target. Experience buckets count seasons observed in the data
before the target season (rookie = 1, 2–3, veteran = 4+). True rookies with
zero MLB history cannot be projected by any of these systems and are
excluded by construction.

**Honest caveats**

- The panel starts in 2015, so experience counts are left-truncated: a
  ten-year veteran in 2022 counts at most 7 prior seasons. Bucket labels
  describe *observed* seasons, not service time.
- 2020 is the 60-game COVID season; it participates in trailing windows and
  Marcel weights at face value.
- League averages are computed from the players present in the Savant
  batting CSV (roughly the 50+ PA population), not all MLB hitters.
- Marcel weights (5/4/3), ballast ({BALLAST_PA:.0f} PA), and the age slopes are the
  classic published constants — nothing here was tuned on the test seasons.
- Home-run errors are in HR per season (counting stat, so playing-time
  error dominates); wOBA errors are in absolute wOBA points.
"""]

    for stat in stats:
        label = STAT_LABELS.get(stat, stat)
        parts.append(f"## {label}\n")
        parts.append(f"### RMSE by season — {label}\n")
        parts.append(_season_table(results, stat, "rmse", seasons, systems))
        parts.append(f"\n### MAE by season — {label}\n")
        parts.append(_season_table(results, stat, "mae", seasons, systems))
        parts.append(f"\n### Eligible predictions per season — {label}\n")
        parts.append(_n_table(results, stat, seasons, systems))
        parts.append(f"\n### By experience bucket (pooled {seasons[0]}–{seasons[-1]}) — {label}\n")
        parts.append(_bucket_table(results, stat, systems))
        parts.append("")

    parts.append(f"""## Calibration — 80% bands

Nominal coverage is {NOMINAL_BAND:.0%}: an actual outcome should land inside the band
80% of the time. Residual bands are fit only on folds strictly before the
evaluated season (folds back to {results["config"]["fold_start"]}), then applied to that season —
fully out-of-sample. The KNN row labeled "model's own output" scores the
p10–p90 band the production endpoint actually returns.
""")
    parts.append(_calibration_table(results, systems))
    parts.append("")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Season-holdout backtest report")
    ap.add_argument("--stats", default="woba,home_run")
    ap.add_argument("--seasons", default="2022-2025", help="target seasons, e.g. 2022-2025")
    ap.add_argument("--fold-start", type=int, default=2018,
                    help="earliest fold (pre-target folds feed the band fit)")
    ap.add_argument("--min-pa", type=int, default=200)
    ap.add_argument("--systems", default=",".join(DEFAULT_SYSTEMS))
    ap.add_argument("--player-limit", type=int, default=None,
                    help="cap eligible players per fold (dev/smoke only)")
    ap.add_argument("--json-out", default=RESULTS_JSON)
    args = ap.parse_args(argv)

    stats = [s.strip() for s in args.stats.split(",") if s.strip()]
    systems = tuple(s.strip() for s in args.systems.split(",") if s.strip())
    first, last = (int(p) for p in args.seasons.split("-"))
    seasons = list(range(first, last + 1))

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    db = SessionLocal()
    try:
        log(f"Running season-holdout backtest: stats={stats} seasons={seasons} "
            f"systems={list(systems)} fold_start={args.fold_start} min_pa={args.min_pa}")
        records, results = run_season_holdout(
            db=db,
            engine=engine,
            stats=stats,
            target_seasons=seasons,
            fold_start=args.fold_start,
            min_pa=args.min_pa,
            systems=systems,
            player_limit=args.player_limit,
            progress=log,
        )
    finally:
        db.close()

    results["generated"] = date.today().isoformat()
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, "w") as fh:
        json.dump(results, fh, indent=2)
    log(f"Wrote raw results JSON to {args.json_out} ({len(records)} prediction records)")

    print(build_markdown(results, seasons, systems, stats))


if __name__ == "__main__":
    main()
