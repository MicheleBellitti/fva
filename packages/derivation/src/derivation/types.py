"""Tipi degli input esterni del DAG di derivazione."""

from typing import Protocol


class DetectorRegistry(Protocol):
    """Registry dei detector con le loro soglie da config. Interfaccia: P2.4."""


class TextEmbedder(Protocol):
    """Testo strutturato dell'evento → vettore 768. Interfaccia: P3.2."""
