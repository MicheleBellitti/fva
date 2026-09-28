"""DAG di percezione: video → tracking in coordinate campo.

Un nodo per stadio, mai per frame: il loop sui frame vive dentro P1 e P4 come generatori.
I nomi delle funzioni sono API pubblica. Ogni stub cita il task che lo implementa.
Vedi `docs/technical-design.md` §4.
"""

from collections.abc import Iterator

import polars as pl
from hamilton.function_modifiers import check_output, config

from perception._pending_core import ClockAlignment
from perception.config import Mode
from perception.types import CropEmbedder, Detector, Frame, KeypointModel, TrackerConfig


def frames(video_uri: str, sample_fps: float) -> Iterator[Frame]:
    """P1 · Decodifica PyAV a `sample_fps`. Non materializza."""
    raise NotImplementedError("P1.1")


def shot_boundaries(frames: Iterator[Frame]) -> pl.DataFrame:
    """P2 · `[t_start, t_end]` da differenze di istogrammi HSV."""
    raise NotImplementedError("P1.2")


def shot_segments(shot_boundaries: pl.DataFrame, frames: Iterator[Frame]) -> pl.DataFrame:
    """P3 · Aggiunge `view_type` e `usable`, un frame per segmento."""
    raise NotImplementedError("P1.3")


def tactical_frames(frames: Iterator[Frame], shot_segments: pl.DataFrame) -> Iterator[Frame]:
    """P4 · Solo i frame dei segmenti usabili, prima della GPU."""
    raise NotImplementedError("P1.4")


def detections_full(tactical_frames: Iterator[Frame], detector: Detector) -> pl.DataFrame:
    """P5 · `[frame, cls, x1, y1, x2, y2, conf]`, YOLO @ 1280 fp16."""
    raise NotImplementedError("P1.7")


@config.when(ball_tiling=True)
def detections_ball__tiled(tactical_frames: Iterator[Frame], detector: Detector) -> pl.DataFrame:
    """P6 · Palla su tile 3x2 a risoluzione nativa."""
    raise NotImplementedError("P1.8")


@config.when(ball_tiling=False)
def detections_ball__untiled(tactical_frames: Iterator[Frame], detector: Detector) -> pl.DataFrame:
    """P6 · Palla sul frame intero, per il live."""
    raise NotImplementedError("P1.8")


def detections(detections_full: pl.DataFrame, detections_ball: pl.DataFrame) -> pl.DataFrame:
    """P7 · Unione, con NMS sulla palla."""
    raise NotImplementedError("P1.8")


def tracks_raw(detections: pl.DataFrame, tracker_cfg: TrackerConfig) -> pl.DataFrame:
    """P8 · Aggiunge `track_id` con BoT-SORT. `track_id` non è un giocatore."""
    raise NotImplementedError("P1.9")


def player_crops(tracks_raw: pl.DataFrame, tactical_frames: Iterator[Frame]) -> pl.DataFrame:
    """P9 · `[track_id, frame, crop]`, crop 128x256 dei soli giocatori, 1 ogni 5 frame."""
    raise NotImplementedError("P1.10")


def team_labels(player_crops: pl.DataFrame, siglip: CropEmbedder) -> pl.DataFrame:
    """P10 · `[track_id, team]`: SigLIP → UMAP → KMeans(2), voto per `track_id`."""
    raise NotImplementedError("P1.10")


def pitch_keypoints(tactical_frames: Iterator[Frame], kp_model: KeypointModel) -> pl.DataFrame:
    """P11 · `[frame, kp_id, x, y, conf]`."""
    raise NotImplementedError("P1.11")


def homography_raw(pitch_keypoints: pl.DataFrame) -> pl.DataFrame:
    """P12 · `[frame, H(9), n_inliers, err]` con RANSAC."""
    raise NotImplementedError("P1.11")


@config.when(mode=Mode.BATCH)
def homography__batch(homography_raw: pl.DataFrame) -> pl.DataFrame:
    """P13 · Gate su inlier ed errore, smoothing con mediana mobile."""
    raise NotImplementedError("P1.11")


@config.when(mode=Mode.LIVE)
def homography__live(homography_raw: pl.DataFrame) -> pl.DataFrame:
    """P13 · Gate su inlier ed errore, smoothing con EMA."""
    raise NotImplementedError("P1.11")


@check_output(range=(0.0, 1.0), importance="warn")
def homography_acceptance_rate(homography: pl.DataFrame) -> float:
    """P14 · Frazione di frame con omografia accettata."""
    raise NotImplementedError("P1.12")


def pitch_tracks(
    tracks_raw: pl.DataFrame,
    team_labels: pl.DataFrame,
    homography: pl.DataFrame,
    team_orientation: pl.DataFrame,
    clock_alignment: ClockAlignment,
) -> pl.DataFrame:
    """P15 · Proietta, filtra `h_ok`, normalizza l'orientamento. Schema §3.2."""
    raise NotImplementedError("P1.13")


@check_output(range=(0.0, 40.0), importance="warn")
def max_player_speed_kmh(pitch_tracks: pl.DataFrame) -> float:
    """P16 · Sopra 40 km/h l'omografia è rotta."""
    raise NotImplementedError("P1.12")


def pitch_tracks_parquet(
    pitch_tracks: pl.DataFrame, tracks_root: str, match_id: str, pipeline_version: str
) -> str:
    """P17 · Scrive la partizione Hive `match_id=…/pipeline_version=…` e ne restituisce il path."""
    raise NotImplementedError("P1.13")
