"""Config della pipeline: `config/base.yaml` più overlay, uniti in ordine.

La config seleziona e parametrizza le varianti del DAG (`@config.when`), non ne cambia
la struttura. Vedi `docs/technical-design.md` §6.
"""

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from perception._pending_core import CameraType

BASE = "base"


class Mode(StrEnum):
    BATCH = "batch"
    LIVE = "live"


class PipelineConfig(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    camera: CameraType
    mode: Mode
    sample_fps: float = Field(gt=0, le=25)
    ball_tiling: bool


def load_config(root: Path, *overlays: str) -> PipelineConfig:
    """Unisce `base` e gli overlay nell'ordine dato: l'ultimo vince, chiave per chiave."""
    merged: dict[str, object] = {}
    for name in (BASE, *overlays):
        data = yaml.safe_load((root / f"{name}.yaml").read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{name}.yaml deve essere una mappa")
        merged |= data
    return PipelineConfig.model_validate(merged)
