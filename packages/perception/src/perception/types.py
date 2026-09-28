"""Tipi degli input esterni del DAG di percezione.

I Protocol sono vuoti finché i task che caricano i modelli non ne fissano l'interfaccia.
"""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

# (frame_idx, t_video in secondi, immagine HxWx3 BGR)
Frame = tuple[int, float, NDArray[np.uint8]]


class Detector(Protocol):
    """YOLO11m residente in VRAM. Interfaccia: P1.7."""


class TrackerConfig(Protocol):
    """Parametri di BoT-SORT. Interfaccia: P1.9."""


class CropEmbedder(Protocol):
    """SigLIP sui crop dei giocatori. Interfaccia: P1.10."""


class KeypointModel(Protocol):
    """Modello dei keypoint del campo. Interfaccia: P1.11."""
