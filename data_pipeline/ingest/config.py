# data_pipeline/ingest/config.py
"""Typed access to data_pipeline/config.toml (stdlib tomllib; no YAML dep)."""
import os
import tomllib
from dataclasses import dataclass, field

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "config.toml")


@dataclass
class StatcastConfig:
    seasons: list[int] = field(default_factory=lambda: [2021, 2022, 2023, 2024, 2025])
    chunk_days: int = 7
    season_start: str = "02-20"
    season_end: str = "11-10"
    delay_seconds: float = 2.0
    max_attempts: int = 3
    retry_backoff_seconds: list[float] = field(default_factory=lambda: [10, 30])


@dataclass
class BatTrackingConfig:
    seasons: list[int] = field(default_factory=lambda: [2024, 2025])
    min_swings: int = 1


@dataclass
class QualityConfig:
    max_duplicate_key_rate: float = 0.005


@dataclass
class PipelineConfig:
    statcast: StatcastConfig = field(default_factory=StatcastConfig)
    bat_tracking: BatTrackingConfig = field(default_factory=BatTrackingConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)


def load_config(path: str | None = None) -> PipelineConfig:
    path = path or os.path.abspath(DEFAULT_PATH)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return PipelineConfig(
        statcast=StatcastConfig(**raw.get("statcast", {})),
        bat_tracking=BatTrackingConfig(**raw.get("bat_tracking", {})),
        quality=QualityConfig(**raw.get("quality", {})),
    )
