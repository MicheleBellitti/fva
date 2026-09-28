"""Segnaposto per tipi che S0.3 porta in `core.models`.

TODO(S0.3): sostituire gli import da questo modulo con quelli da `core` e cancellarlo.
"""

from enum import StrEnum

from pydantic import BaseModel


class CameraType(StrEnum):
    """Valori ammessi da `matches.camera_type`."""

    BROADCAST = "broadcast"
    TACTICAL_FIXED = "tactical_fixed"


class ClockAlignment(BaseModel):
    """I quattro timestamp di `matches` (secondi dall'inizio del video)."""

    model_config = {"extra": "forbid"}

    half1_kickoff_s: float
    half1_end_s: float
    half2_kickoff_s: float
    half2_end_s: float
