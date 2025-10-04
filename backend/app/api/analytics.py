# backend/app/api/analytics.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import create_engine

from ..db.database import get_db, DATABASE_URL
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

from .schemas import (
    validate_compare_payload,
    validate_predict_payload,
    validate_compare_multi_payload,
    make_chart_response,
)

router = APIRouter(prefix="/api", tags=["analytics"])


@router.post("/compare")
async def compare_players(request: Request, db=Depends(get_db)):
    payload = await request.json()
    data = validate_compare_payload(payload)
    try:
        result = compare_players_by_season(
            db,
            player_ids=data["player_ids"],
            stat=data["stat"],
            year=data["year"],
            start_year=data["start_year"],
            end_year=data["end_year"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return make_chart_response(
        result["chart_type"],
        result["series"],
        "Comparison across the selected window.",
        meta=result.get("meta"),
    )


@router.post("/predict")
async def predict(request: Request, db=Depends(get_db)):
    payload = await request.json()
    data = validate_predict_payload(payload)

    try:
        # NEW: Aging curve + KNN comparables (implements your write-up flow)
        if data["method"] == "aging_knn":
            engine = create_engine(DATABASE_URL)
            series, meta = project_stat_aging_knn(
                db=db,
                db_engine=engine,
                player_id=data["player_id"],
                stat=data["stat"],
                horizon=data["horizon"],
                lookback=data["years"],
                k=25,
                age_cap=42,
                alpha_comps=0.5,
            )
            ttl = f"{stat_label(data['stat'])} forecast (aging+KNN, {data['horizon']} yrs)"
            meta = {
                **(meta or {}),
                "label_map": label_map_for([data["stat"]]),
                "title": ttl,
                "bands": {"p10": "lower", "p90": "upper"},
            }
            return make_chart_response(
                "line",
                series,
                "Aging curve blended with KNN comparables.",
                meta=meta,
            )

        # ML regressors already in your project
        if data["method"] == "ml":
            res = predict_player_stat_ml(db, data["player_id"], data["stat"], lookback=data["lookback"])
            return make_chart_response(
                res["chart_type"], res["series"], "ML projection vs. league baseline.", meta=res.get("meta")
            )

        if data["method"] == "ml_prob":
            res = predict_player_above_avg_prob(db, data["player_id"], data["stat"], lookback=data["lookback"])
            return make_chart_response(
                res["chart_type"], res["series"], "Probability of being above league average.", meta=res.get("meta")
            )

        # Baseline: series forecast (horizon > 1)
        if data["horizon"] > 1:
            path = predict_player_stat_series(
                db,
                data["player_id"],
                data["stat"],
                lookback_years=data["years"],
                horizon=data["horizon"],
            )
            series = [
                {
                    "id": "Projected " + data["stat"],
                    "data": [{"x": y, "y": float(v)} for (y, v) in path],
                }
            ]
            meta = {
                "label_map": label_map_for([data["stat"]]),
                "title": f"{stat_label(data['stat'])} forecast ({data['horizon']} yrs)",
            }
            return make_chart_response(
                "line",
                series,
                "Linear-trend forecast using last {} seasons.".format(data["years"]),
                meta=meta,
            )

        # Baseline: single-bar projection (trailing average)
        v = predict_player_stat(db, data["player_id"], data["stat"], data["years"])
        y = v if v is not None else 0.0
        series = [{"id": "Projected " + data["stat"], "data": [{"x": "Next season", "y": y}]}]
        meta = {"label_map": label_map_for([data["stat"]]), "title": "Projected " + stat_label(data["stat"])}
        return make_chart_response("bar", series, "Baseline projection uses trailing average.", meta=meta)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leaderboard")
async def api_leaderboard(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = leaderboard(
            db,
            p.get("stat"),
            p.get("year"),
            p.get("limit", 10),
            p.get("min_pa"),
            p.get("order", "desc"),  # supports top/bottom
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Leaderboard.", meta=res.get("meta"))


@router.post("/leaderboard_range")
async def api_leaderboard_range(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = leaderboard_range(
            db,
            p.get("stat"),
            p.get("start_year"),
            p.get("end_year"),
            p.get("limit", 10),
            p.get("agg", "sum"),
            p.get("order", "desc"),
            p.get("min_pa"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Leaderboard (range).", meta=res.get("meta"))


@router.post("/career_arc")
async def api_career_arc(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = career_arc(db, p.get("player_id"), p.get("stat"), p.get("start_year"), p.get("end_year"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Career arc.", meta=res.get("meta"))


@router.post("/rolling_mean")
async def api_rolling_mean(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = rolling_mean(
            db,
            p.get("player_id"),
            p.get("stat"),
            p.get("window", 3),
            p.get("start_year"),
            p.get("end_year"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Rolling mean.", meta=res.get("meta"))


@router.post("/yoy_change")
async def api_yoy_change(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = yoy_change(db, p.get("player_id"), p.get("stat"), p.get("start_year"), p.get("end_year"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Year-over-year change.", meta=res.get("meta"))


@router.post("/percentile")
async def api_percentile(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = percentile_rank(db, p.get("player_ids", []), p.get("stat"), p.get("year"), p.get("min_pa"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Percentiles.", meta=res.get("meta"))


@router.post("/improvement")
async def api_improvement(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = improvement_leaderboard(
            db,
            p.get("stat"),
            p.get("year_start"),
            p.get("year_end"),
            p.get("limit", 10),
            p.get("min_pa"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Most improved.", meta=res.get("meta"))


@router.post("/rate_per_pa")
async def api_rate_per_pa(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = rate_per_pa(
            db,
            p.get("player_ids", []),
            p.get("numerator_stat"),
            p.get("year"),
            p.get("per", 600),
            p.get("pa_col", "plate_appearances"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Rate per PA.", meta=res.get("meta"))


@router.post("/radar")
async def api_radar(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = radar_multistat(db, p.get("player_ids", []), p.get("stats", []), p.get("year"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "Multi-stat radar.", meta=res.get("meta"))


@router.post("/histogram")
async def api_histogram(request: Request, db=Depends(get_db)):
    p = await request.json()
    try:
        res = stat_histogram(db, p.get("stat"), p.get("year"), p.get("bins", 12), p.get("min_pa"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return make_chart_response(res["chart_type"], res["series"], "League distribution.", meta=res.get("meta"))


@router.post("/compare_multi")
async def api_compare_multi(request: Request, db=Depends(get_db)):
    p = validate_compare_multi_payload(await request.json())
    try:
        res = compare_multi(
            db,
            players=p["players"],
            stats=p["stats"],
            year=p["year"],
            start_year=p["start_year"],
            end_year=p["end_year"],
            mode=p["mode"],
            layout=p["layout"],
            normalize=p["normalize"],
            window=p["window"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if res.get("chart_type") == "facet":
        return make_chart_response(
            "facet", [], "Multi-stat over time — rendered as facets.", meta=res.get("meta"), facets=res.get("facets")
        )
    return make_chart_response(res["chart_type"], res["series"], "Flexible comparison.", res.get("meta"))
