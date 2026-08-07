# backend/app/api/schemas.py
"""
Typed API contract (Pydantic v2).

Every data endpoint returns the canonical chart payload:

    { chart_type, series, narration, meta, ai_source, facets? }

modeled by ChartResponse and wired into the routers via `response_model=`,
so FastAPI validates responses and renders the schema at /docs. Request
bodies are per-endpoint models below.

SCHEMA_VERSION is serialized on every response; bump it when the payload
shape changes in a way the frontend must react to.
"""
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1"

# Trimmed, non-empty user-supplied identifiers (stat names, column names).
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

ChartType = Literal["bar", "line", "radar", "facet"]


# ---------------------------------------------------------------------------
# Response contract — the canonical chart payload
# ---------------------------------------------------------------------------

class ChartPoint(BaseModel):
    """One datum; extra keys (e.g. band values) pass through untouched."""

    model_config = ConfigDict(extra="allow")

    x: Union[str, int, float, None] = None
    y: Optional[float] = None


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    data: list[ChartPoint] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return v if isinstance(v, str) else str(v)


class ChartFacet(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: Optional[str] = None
    series: list[ChartSeries] = Field(default_factory=list)


class ChartResponse(BaseModel):
    """Canonical payload rendered by the frontend ChartRenderer."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    chart_type: ChartType
    series: list[ChartSeries] = Field(default_factory=list)
    narration: str = ""
    meta: Optional[dict[str, Any]] = None
    facets: Optional[list[ChartFacet]] = None
    ai_source: Optional[str] = None
    # Populated only by /api/prompt?debug=1 on the agent route.
    plan: Optional[dict[str, Any]] = None


def make_chart_response(chart_type, series, narration="", meta=None, facets=None):
    """Assemble the canonical payload; response_model validates it on the way out."""
    out = {
        "chart_type": chart_type,
        "series": series,
        "narration": narration,
    }
    if meta:
        out["meta"] = meta
    if facets is not None:
        out["facets"] = facets
    return out


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class YearWindow(BaseModel):
    """year XOR (start_year AND end_year), shared by compare-style requests."""

    year: Optional[int] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    @model_validator(mode="after")
    def _validate_window(self):
        if self.year and (self.start_year or self.end_year):
            raise ValueError("Provide either 'year' OR 'start_year'+'end_year', not both.")
        if (self.start_year and not self.end_year) or (self.end_year and not self.start_year):
            raise ValueError("Provide both 'start_year' and 'end_year' for a range.")
        return self


class PromptRequest(BaseModel):
    text: NonEmptyStr


class CompareRequest(YearWindow):
    player_ids: list[int] = Field(min_length=1)
    stat: NonEmptyStr


class PredictRequest(BaseModel):
    player_id: int
    stat: NonEmptyStr
    years: int = Field(3, ge=1)
    horizon: int = Field(1, ge=1)
    method: Literal["baseline", "ml", "ml_prob", "aging_knn"] = "baseline"
    lookback: Optional[int] = None  # defaults to `years`

    @model_validator(mode="after")
    def _default_lookback(self):
        if self.lookback is None:
            self.lookback = self.years
        return self


class CompareMultiRequest(YearWindow):
    players: list[Union[int, str]] = Field(
        min_length=1, validation_alias=AliasChoices("players", "player_ids")
    )
    stats: list[NonEmptyStr] = Field(min_length=1)
    mode: Literal["players_by_stat", "stats_by_player"] = "players_by_stat"
    layout: Literal["grouped", "stacked"] = "grouped"
    normalize: Optional[dict[str, Any]] = None
    window: Optional[int] = None

    @field_validator("stats", mode="before")
    @classmethod
    def _stats_to_list(cls, v):
        # Accept a list or a comma-separated string.
        if isinstance(v, str):
            v = v.split(",")
        if isinstance(v, list):
            return [str(s).strip() for s in v if str(s).strip()]
        return v


class LeaderboardRequest(BaseModel):
    stat: NonEmptyStr
    year: Optional[int] = None
    limit: int = Field(10, ge=1)
    min_pa: Optional[int] = Field(None, ge=0)
    order: Literal["asc", "desc"] = "desc"


class LeaderboardRangeRequest(BaseModel):
    stat: NonEmptyStr
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    limit: int = Field(10, ge=1)
    agg: Literal["sum", "avg"] = "sum"
    order: Literal["asc", "desc"] = "desc"
    min_pa: Optional[int] = Field(None, ge=0)


class CareerArcRequest(BaseModel):
    player_id: int
    stat: NonEmptyStr
    start_year: Optional[int] = None
    end_year: Optional[int] = None


class RollingMeanRequest(CareerArcRequest):
    window: int = Field(3, ge=1)


class YoyChangeRequest(CareerArcRequest):
    pass


class PercentileRequest(BaseModel):
    player_ids: list[int] = Field(default_factory=list)
    stat: NonEmptyStr
    year: Optional[int] = None
    min_pa: Optional[int] = Field(None, ge=0)


class ImprovementRequest(BaseModel):
    stat: NonEmptyStr
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    limit: int = Field(10, ge=1)
    min_pa: Optional[int] = Field(None, ge=0)


class RatePerPaRequest(BaseModel):
    player_ids: list[int] = Field(default_factory=list)
    numerator_stat: NonEmptyStr
    year: Optional[int] = None
    per: int = Field(600, ge=1)
    pa_col: NonEmptyStr = "plate_appearances"


class RadarRequest(BaseModel):
    player_ids: list[int] = Field(default_factory=list)
    stats: list[NonEmptyStr] = Field(default_factory=list)
    year: Optional[int] = None


class HistogramRequest(BaseModel):
    stat: NonEmptyStr
    year: Optional[int] = None
    bins: int = Field(12, ge=1)
    min_pa: Optional[int] = Field(None, ge=0)


class BacktestRequest(BaseModel):
    stat: NonEmptyStr
    start_year: int
    end_year: int
    lookback: int = Field(3, ge=1)
    method: Literal["baseline", "linear"] = "baseline"
    min_pa: Optional[int] = Field(None, ge=0)

    @field_validator("method", mode="before")
    @classmethod
    def _lower_method(cls, v):
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_years(self):
        if self.end_year <= self.start_year:
            raise ValueError("'end_year' must be greater than 'start_year'.")
        return self
