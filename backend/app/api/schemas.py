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

# "clarify" is not a chart: it asks the user to resolve an ambiguity
# (which player / which stats) before a chart can be produced. Additive to
# the v1 contract — clients that predate it fall through to their default
# branch and show the narration.
ChartType = Literal["bar", "line", "radar", "facet", "clarify"]


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


class RadarRow(BaseModel):
    """One radar spoke: {"stat": <slug>, "<series name>": <value>, ...}.

    Nivo's ResponsiveRadar consumes rows keyed by spoke ("stat") with one
    extra key per polygon — a different shape from ChartSeries. Radar
    endpoints were 500ing on response validation until this variant
    existed in the contract.
    """

    model_config = ConfigDict(extra="allow")

    stat: str


class ClarifyOption(BaseModel):
    """One clickable choice. `value` is the exact hint fragment the client
    sends back in PromptRequest.hints when this option is chosen."""

    model_config = ConfigDict(extra="allow")

    label: str
    description: Optional[str] = None
    value: dict[str, Any] = Field(default_factory=dict)


class ClarifyQuestion(BaseModel):
    """A question the preflight needs answered before charting: which
    player a mention refers to, or which stats to compare."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["player", "stat"]
    prompt: str
    mention: Optional[str] = None       # the text span this disambiguates
    multi: bool = False                 # stat questions allow multi-select
    options: list[ClarifyOption] = Field(default_factory=list)


class ChartResponse(BaseModel):
    """Canonical payload rendered by the frontend ChartRenderer."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    chart_type: ChartType
    series: list[Union[ChartSeries, RadarRow]] = Field(default_factory=list)
    narration: str = ""
    meta: Optional[dict[str, Any]] = None
    facets: Optional[list[ChartFacet]] = None
    ai_source: Optional[str] = None
    # Present only when chart_type == "clarify".
    clarification: Optional[list[ClarifyQuestion]] = None
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


class PlayerHint(BaseModel):
    """Pins one name mention to a resolution, echoing a ClarifyOption.value.
    player_id -> a chartable local player; statsapi_id/name only -> a real
    person with no data in the covered window (the graceful-gap path).
    debut/team ride along so the gap message stays specific."""

    mention: NonEmptyStr
    player_id: Optional[int] = None
    statsapi_id: Optional[int] = None
    name: Optional[str] = None
    debut: Optional[str] = None
    team: Optional[str] = None


class PromptHints(BaseModel):
    players: list[PlayerHint] = Field(default_factory=list)
    stats: list[NonEmptyStr] = Field(default_factory=list)


class PromptRequest(BaseModel):
    text: NonEmptyStr
    # Clarification round-trip: answers to a previous "clarify" response.
    hints: Optional[PromptHints] = None


class CompareRequest(YearWindow):
    player_ids: list[int] = Field(min_length=1)
    stat: NonEmptyStr


class PredictRequest(BaseModel):
    player_id: int
    stat: NonEmptyStr
    years: int = Field(3, ge=1)
    horizon: int = Field(1, ge=1)
    # Marcel is the default single-season baseline (Phase 4);
    # "baseline" = the older trailing-mean projection.
    method: Literal["marcel", "baseline", "ml", "ml_prob", "aging_knn"] = "marcel"
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


class BatSpeedProfileRequest(BaseModel):
    """Bat-tracking skill profile (radar). `player` is an MLBAM id or a
    name fragment; season defaults to the latest with bat-tracking data."""

    player: Union[int, NonEmptyStr]
    season: Optional[int] = None
    min_swings: int = Field(50, ge=0)


class BlastLeaderboardRequest(BaseModel):
    stat: NonEmptyStr = "blast_rate"
    season: Optional[int] = None
    limit: int = Field(10, ge=1)
    min_swings: int = Field(100, ge=0)
    order: Literal["asc", "desc"] = "desc"


class BatSpeedProductionRequest(BaseModel):
    season: Optional[int] = None
    production_stat: NonEmptyStr = "woba"
    min_swings: int = Field(100, ge=0)


class BacktestRequest(BaseModel):
    stat: NonEmptyStr
    start_year: int
    end_year: int
    lookback: int = Field(3, ge=1)
    method: Literal["baseline", "linear"] = "baseline"
    min_pa: Optional[int] = Field(None, ge=0)
    # mode="compare": season-holdout comparison of forecast systems
    # (naive / trailing / marcel by default; add "knn" explicitly — it is
    # slow enough that the offline report generator is the better home).
    mode: Literal["single", "compare"] = "single"
    systems: Optional[list[Literal["naive", "trailing", "marcel", "knn"]]] = None

    @field_validator("method", mode="before")
    @classmethod
    def _lower_method(cls, v):
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_years(self):
        if self.end_year <= self.start_year:
            raise ValueError("'end_year' must be greater than 'start_year'.")
        return self
