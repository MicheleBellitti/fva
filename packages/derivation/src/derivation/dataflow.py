"""DAG di derivazione: tracking → possessi, eventi, metriche.

Lavora su `pl.LazyFrame` letti dal Parquet di P17 e colleziona una volta alla fine.
I nomi delle funzioni sono API pubblica. Ogni stub cita il task che lo implementa.
Vedi `docs/technical-design.md` §4.
"""

import polars as pl
from sqlalchemy import Engine

from derivation._pending_core import Event
from derivation.types import DetectorRegistry, TextEmbedder


def ball_track(pitch_tracks: pl.LazyFrame) -> pl.LazyFrame:
    """D1 · `[t, x, y, conf, interpolated]`: Kalman + interpolazione su gap <= 1 s."""
    raise NotImplementedError("P2.1")


def ball_carrier(pitch_tracks: pl.LazyFrame, ball_track: pl.LazyFrame) -> pl.LazyFrame:
    """D2 · `[t, track_id, team, dist]`: `join_asof` palla → giocatore entro 2 m."""
    raise NotImplementedError("P2.2")


def possessions(ball_carrier: pl.LazyFrame) -> pl.LazyFrame:
    """D3 · `[t_start, t_end, team, ...]`: run-length su `team` con isteresi."""
    raise NotImplementedError("P2.3")


def possessions_fallback(pitch_tracks: pl.LazyFrame) -> pl.LazyFrame:
    """D4 · Possesso dal movimento collettivo quando la palla manca. Confidence 0.4."""
    raise NotImplementedError("P2.10")


def possessions_merged(
    possessions: pl.LazyFrame, possessions_fallback: pl.LazyFrame
) -> pl.LazyFrame:
    """D5 · D3 dove disponibile, D4 nei buchi."""
    raise NotImplementedError("P2.10")


def team_shape(pitch_tracks: pl.LazyFrame) -> pl.LazyFrame:
    """D6 · Centroide, ampiezza, profondità, linea; solo frame con >= 7 visibili per squadra."""
    raise NotImplementedError("P2.8")


def events_geometric(
    possessions_merged: pl.LazyFrame,
    team_shape: pl.LazyFrame,
    ball_track: pl.LazyFrame,
    registry: DetectorRegistry,
) -> list[Event]:
    """D7 · Corner, rimessa, fuori campo, cambio possesso, kickoff: regole pure."""
    raise NotImplementedError("P2.5")


def events_statistical(
    possessions_merged: pl.LazyFrame,
    team_shape: pl.LazyFrame,
    ball_track: pl.LazyFrame,
    registry: DetectorRegistry,
) -> list[Event]:
    """D8 · Cross, tiro, passaggio ultimo terzo, transizione, pressing: regole con soglie."""
    raise NotImplementedError("P2.9")


def events(events_geometric: list[Event], events_statistical: list[Event]) -> pl.DataFrame:
    """D9 · Schema `events`, dedup dello stesso tipo entro 2 s."""
    raise NotImplementedError("P2.6")


def team_metrics(team_shape: pl.LazyFrame, possessions_merged: pl.LazyFrame) -> pl.DataFrame:
    """D10 · Finestre da 5 min con `coverage`."""
    raise NotImplementedError("P3.1")


def event_embeddings(
    events: pl.DataFrame, pitch_tracks: pl.LazyFrame, text_embedder: TextEmbedder
) -> pl.DataFrame:
    """D11 · `[event_id, embedding]`: testo strutturato + contesto spaziale → vettore."""
    raise NotImplementedError("P3.2")


def persist(
    events: pl.DataFrame,
    team_metrics: pl.DataFrame,
    event_embeddings: pl.DataFrame,
    engine: Engine,
    pipeline_version: str,
) -> None:
    """D12 · Upsert su Postgres per `pipeline_version`. Mai sovrascrivere un'altra versione."""
    raise NotImplementedError("P2.6")
