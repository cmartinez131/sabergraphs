# backend/app/api/analytics.py
from fastapi import APIRouter, Depends, HTTPException

from ..db.database import get_db, engine
from ..toolkit.stats import (
    compare_players_by_season,
    leaderboard,
    leaderboard_range,
    career_arc,
    rolling_mean,
    yoy_change,
    percentile_rank,
    improvement_leaderboard,
    rate_per_pa,
    radar_multistat,
    stat_histogram,
    compare_multi,
    label_map_for,
    stat_label,
)
from ..toolkit.projections import (
    predict_player_stat,
    predict_player_stat_series,
    predict_player_stat_ml,
    predict_player_above_avg_prob,
)
from ..toolkit.aging import project_stat_aging_knn
from ..toolkit.backtest import knn_band_calibration
from ..toolkit.marcel import marcel_project

from ..toolkit.battracking import (
    bat_speed_profile,
    bat_speed_vs_production,
    blast_leaderboard,
)
from .schemas import (
    BatSpeedProductionRequest,
    BatSpeedProfileRequest,
    BlastLeaderboardRequest,
    ChartResponse,
    CompareRequest,
    PredictRequest,
    CompareMultiRequest,
    LeaderboardRequest,
    LeaderboardRangeRequest,
    CareerArcRequest,
    RollingMeanRequest,
    YoyChangeRequest,
    PercentileRequest,
    ImprovementRequest,
    RatePerPaRequest,
    RadarRequest,
    HistogramRequest,
    make_chart_response,
)

router = APIRouter(prefix="/api", tags=["analytics"])


@router.post("/compare", response_model=ChartResponse)
async def compare_players(body: CompareRequest, db=Depends(get_db)):
    try:
        result = compare_players_by_season(
            db,
            player_ids=body.player_ids,
            stat=body.stat,
            year=body.year,
            start_year=body.start_year,
            end_year=body.end_year,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return make_chart_response(
        result["chart_type"],
        result["series"],
        "Comparison across the selected window.",
        meta=result.get("meta"),
    )


@router.post("/predict", response_model=ChartResponse)
async def predict(body: PredictRequest, db=Depends(get_db)):
    try:
        # Aging curve + KNN comparables (shared pooled engine, not per-request)
        if body.method == "aging_knn":
            series, meta = project_stat_aging_knn(
                db=db,
                db_engine=engine,
                player_id=body.player_id,
                stat=body.stat,
                horizon=body.horizon,
                lookback=body.years,
                k=25,
                age_cap=42,
                alpha_comps=0.5,
            )
            ttl = f"{stat_label(body.stat)} forecast (aging+KNN, {body.horizon} yrs)"
            meta = {
                **(meta or {}),
                "label_map": label_map_for([body.stat]),
                "title": ttl,
                "bands": {"p10": "lower", "p90": "upper"},
                "band_calibration": knn_band_calibration(),
            }
            return make_chart_response(
                "line",
                series,
                "Aging curve blended with KNN comparables. The p10–p90 band "
                "is experimental: backtested coverage came in well below the "
                "nominal 80% (details in meta.band_calibration).",
                meta=meta,
            )

        # ML regressors
        if body.method == "ml":
            res = predict_player_stat_ml(db, body.player_id, body.stat, lookback=body.lookback)
            return make_chart_response(
                res["chart_type"], res["series"], "ML projection vs. league baseline.", meta=res.get("meta")
            )

        if body.method == "ml_prob":
            res = predict_player_above_avg_prob(db, body.player_id, body.stat, lookback=body.lookback)
            return make_chart_response(
                res["chart_type"], res["series"], "Probability of being above league average.", meta=res.get("meta")
            )

        # Baseline: series forecast (horizon > 1)
        if body.horizon > 1:
            path = predict_player_stat_series(
                db,
                body.player_id,
                body.stat,
                lookback_years=body.years,
                horizon=body.horizon,
            )
            series = [
                {
                    "id": "Projected " + body.stat,
                    "data": [{"x": y, "y": float(v)} for (y, v) in path],
                }
            ]
            meta = {
                "label_map": label_map_for([body.stat]),
                "title": f"{stat_label(body.stat)} forecast ({body.horizon} yrs)",
            }
            return make_chart_response(
                "line",
                series,
                "Linear-trend forecast using last {} seasons.".format(body.years),
                meta=meta,
            )

        # Marcel (default): 5/4/3 recency weights, league-mean regression,
        # age adjustment. Falls back to the trailing mean when the player has
        # no seasons in the 3-year window.
        if body.method == "marcel":
            proj = marcel_project(db, body.player_id, body.stat)
            if proj is not None:
                series = [{
                    "id": "Projected " + body.stat,
                    "data": [{"x": "Next season", "y": proj["proj_value"]}],
                }]
                meta = {
                    "label_map": label_map_for([body.stat]),
                    "title": "Projected " + stat_label(body.stat),
                    "method": "marcel",
                    "marcel": {
                        k: proj[k]
                        for k in ("target_year", "proj_rate", "proj_pa", "age_mult",
                                  "age_at_target", "weighted_pa", "n_seasons",
                                  "league_rate", "weights", "ballast_pa", "kind")
                    },
                }
                return make_chart_response(
                    "bar", series,
                    "Marcel projection: 3-season 5/4/3 weighting, regressed to "
                    "the league mean, age-adjusted.",
                    meta=meta,
                )

        # Baseline: single-bar projection (trailing average) — also the
        # fallback when Marcel has no recent history.
        v = predict_player_stat(db, body.player_id, body.stat, body.years)
        y = v if v is not None else 0.0
        series = [{"id": "Projected " + body.stat, "data": [{"x": "Next season", "y": y}]}]
        meta = {
            "label_map": label_map_for([body.stat]),
            "title": "Projected " + stat_label(body.stat),
            "method": "trailing_mean",
        }
        return make_chart_response("bar", series, "Baseline projection uses trailing average.", meta=meta)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leaderboard", response_model=ChartResponse)
async def api_leaderboard(body: LeaderboardRequest, db=Depends(get_db)):
    try:
        res = leaderboard(
            db,
            body.stat,
            body.year,
            body.limit,
            body.min_pa,
            body.order,  # supports top/bottom
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Leaderboard.", meta=res.get("meta"))


@router.post("/leaderboard_range", response_model=ChartResponse)
async def api_leaderboard_range(body: LeaderboardRangeRequest, db=Depends(get_db)):
    try:
        res = leaderboard_range(
            db,
            body.stat,
            body.start_year,
            body.end_year,
            body.limit,
            body.agg,
            body.order,
            body.min_pa,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Leaderboard (range).", meta=res.get("meta"))


@router.post("/career_arc", response_model=ChartResponse)
async def api_career_arc(body: CareerArcRequest, db=Depends(get_db)):
    try:
        res = career_arc(db, body.player_id, body.stat, body.start_year, body.end_year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Career arc.", meta=res.get("meta"))


@router.post("/rolling_mean", response_model=ChartResponse)
async def api_rolling_mean(body: RollingMeanRequest, db=Depends(get_db)):
    try:
        res = rolling_mean(
            db,
            body.player_id,
            body.stat,
            body.window,
            body.start_year,
            body.end_year,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Rolling mean.", meta=res.get("meta"))


@router.post("/yoy_change", response_model=ChartResponse)
async def api_yoy_change(body: YoyChangeRequest, db=Depends(get_db)):
    try:
        res = yoy_change(db, body.player_id, body.stat, body.start_year, body.end_year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Year-over-year change.", meta=res.get("meta"))


@router.post("/percentile", response_model=ChartResponse)
async def api_percentile(body: PercentileRequest, db=Depends(get_db)):
    try:
        res = percentile_rank(db, body.player_ids, body.stat, body.year, body.min_pa)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Percentiles.", meta=res.get("meta"))


@router.post("/improvement", response_model=ChartResponse)
async def api_improvement(body: ImprovementRequest, db=Depends(get_db)):
    try:
        res = improvement_leaderboard(
            db,
            body.stat,
            body.year_start,
            body.year_end,
            body.limit,
            body.min_pa,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Most improved.", meta=res.get("meta"))


@router.post("/rate_per_pa", response_model=ChartResponse)
async def api_rate_per_pa(body: RatePerPaRequest, db=Depends(get_db)):
    try:
        res = rate_per_pa(
            db,
            body.player_ids,
            body.numerator_stat,
            body.year,
            body.per,
            body.pa_col,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Rate per PA.", meta=res.get("meta"))


@router.post("/radar", response_model=ChartResponse)
async def api_radar(body: RadarRequest, db=Depends(get_db)):
    try:
        res = radar_multistat(db, body.player_ids, body.stats, body.year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Multi-stat radar.", meta=res.get("meta"))


@router.post("/histogram", response_model=ChartResponse)
async def api_histogram(body: HistogramRequest, db=Depends(get_db)):
    try:
        res = stat_histogram(db, body.stat, body.year, body.bins, body.min_pa)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "League distribution.", meta=res.get("meta"))


@router.post("/compare_multi", response_model=ChartResponse)
async def api_compare_multi(body: CompareMultiRequest, db=Depends(get_db)):
    try:
        res = compare_multi(
            db,
            players=body.players,
            stats=body.stats,
            year=body.year,
            start_year=body.start_year,
            end_year=body.end_year,
            mode=body.mode,
            layout=body.layout,
            normalize=body.normalize,
            window=body.window,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if res.get("chart_type") == "facet":
        return make_chart_response(
            "facet", [], "Multi-stat over time — rendered as facets.", meta=res.get("meta"), facets=res.get("facets")
        )
    return make_chart_response(res["chart_type"], res["series"], "Flexible comparison.", res.get("meta"))


# ----------------- Bat-tracking mart endpoints (Phase 5) -----------------

@router.post("/bat_speed_profile", response_model=ChartResponse)
async def api_bat_speed_profile(body: BatSpeedProfileRequest, db=Depends(get_db)):
    try:
        res = bat_speed_profile(
            db, player=body.player, season=body.season, min_swings=body.min_swings
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(
        res["chart_type"], res["series"],
        "Percentile skill profile vs qualified swingers.", meta=res.get("meta"),
    )


@router.post("/blast_leaderboard", response_model=ChartResponse)
async def api_blast_leaderboard(body: BlastLeaderboardRequest, db=Depends(get_db)):
    try:
        res = blast_leaderboard(
            db, season=body.season, stat=body.stat, limit=body.limit,
            min_swings=body.min_swings, order=body.order,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(
        res["chart_type"], res["series"],
        "Bat-tracking leaderboard with a minimum-swing qualifier.",
        meta=res.get("meta"),
    )


@router.post("/bat_speed_production", response_model=ChartResponse)
async def api_bat_speed_production(body: BatSpeedProductionRequest, db=Depends(get_db)):
    try:
        res = bat_speed_vs_production(
            db, season=body.season, production_stat=body.production_stat,
            min_swings=body.min_swings,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(
        res["chart_type"], res["series"],
        "Mean production by bat-speed bin across the league.",
        meta=res.get("meta"),
    )
