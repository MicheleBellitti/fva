# Football Video Assistant — Technical Design

*Complementa `architecture.md`. Qui: hardware, framework, storage, micro-step, DAG e agente nel dettaglio.*

---

## 1. Architettura HW/SW

### 1.1 Sviluppo (una macchina, RTX 4070 12 GB)

```
┌─────────────────────── host ───────────────────────┐
│  GPU worker (processo Python, accesso diretto CUDA) │
│  ├─ Hamilton driver                                 │
│  └─ modelli residenti: YOLO · keypoint · SigLIP     │
│                                                     │
│  docker compose                                     │
│  ├─ postgres:16 + pgvector                          │
│  ├─ minio            (S3 locale)                    │
│  ├─ langfuse         (tracing LLM)                  │
│  ├─ burr-ui          (tracing agente)               │
│  ├─ api              (FastAPI)                      │
│  └─ web              (Next.js)                      │
└─────────────────────────────────────────────────────┘
```

Il worker GPU gira **sull'host, non in container**, almeno in Fase 1: evita il runtime NVIDIA in Docker, i problemi di versione CUDA, e rende il debugging con breakpoint banale. Si containerizza in Fase 3, quando la pipeline è stabile.

**Budget VRAM in inferenza** (tutti i modelli residenti insieme):

| Modello | VRAM | Note |
|---|---|---|
| YOLO11m @ 1280, fp16 | ~3 GB | batch 8 frame |
| Ball detector (tile) | ~1 GB | stesso modello, input diverso |
| Keypoint campo | ~1 GB | |
| SigLIP base | ~1.5 GB | solo sui crop, batch 256 |
| ReID BoT-SORT | ~0.5 GB | |
| **Totale** | **~7 GB** | margine comodo su 12 |

**Budget VRAM in training** YOLO11m @ 1280: batch 8 ≈ 10-11 GB. Stretto; se va in OOM, batch 6 con accumulo. Non addestrate mentre il worker è attivo.

**Throughput atteso** (10 fps, solo frame tattici ≈ 40k/partita): detection ~60 fps in fp16 → 11 min; tile palla ×3 → +15 min; keypoint ~120 fps → 6 min; SigLIP sui crop → 3 min; tracking e derivazione su CPU → 5 min. **~40 minuti/partita**, coerente con le stime precedenti.

### 1.2 Produzione

| Componente | Dove | Perché |
|---|---|---|
| `ingest-worker` | GPU on-prem (la 4070) o noleggio orario | batch asincrono, nessuno aspetta |
| `api` | Cloud Run / Container Apps | CPU, scala a zero |
| Postgres + pgvector | gestito (Neon, RDS, Cloud SQL) | un solo DB |
| Object storage | S3 / R2 | video, Parquet, pesi |
| CDN | davanti all'HLS | i segmenti sono la banda |
| Langfuse | cloud o self-hosted | |

Nessuna GPU in produzione lato API: l'assistente è solo query SQL + chiamate LLM.

---

## 2. Framework e librerie

### 2.1 Polars, non pandas — sì, ed è la scelta giusta

I dati di tracking sono milioni di righe colonnari con operazioni a finestra, group-by per `track_id`, e join temporali. È il profilo esatto per cui Polars esiste:

- **Lazy + predicate pushdown su Parquet partizionato**: `scan_parquet("tracks/", hive_partitioning=True).filter(pl.col("match_id") == x)` legge solo i file giusti.
- **`join_asof`**: assegnare a ogni frame la posizione della palla al giocatore più vicino è un asof join, che in pandas è goffo e lento.
- **`over()` e `rolling_*`**: le metriche a finestra mobile per squadra sono espressioni native, multi-thread, senza `apply`.
- **Arrow-native**: zero copie verso Parquet e pgvector.

Hamilton ha un'estensione Polars ufficiale (`h_polars`) — i nodi possono restituire `pl.DataFrame` e `pl.LazyFrame` con validazione di tipo. Pandas resta solo dove una libreria lo impone (raro, e si converte al bordo).

**Regola pratica**: i nodi di percezione restituiscono `pl.DataFrame` eager (i dati stanno in memoria: 800k righe × 10 colonne ≈ 60 MB); i nodi di derivazione lavorano su `pl.LazyFrame` e collezionano una volta alla fine.

### 2.2 Stack completo

**Core**

| | Scelta | Note |
|---|---|---|
| Python | 3.12 | |
| Package manager | `uv` workspace | monorepo, lockfile unico |
| Dataframe | **Polars** | |
| Modelli dati | Pydantic v2 | `extra="forbid"` ovunque |
| Config | Pydantic Settings + YAML | vedi sezione 6 |
| Lint / type | ruff, pyright strict | |

**Percezione** <span style="color:#E8B33C">Dev A</span>

| | Scelta | Note |
|---|---|---|
| Decodifica video | **PyAV** | seek preciso, più veloce di OpenCV per lo streaming di frame |
| Transcodifica / HLS | ffmpeg (subprocess) | |
| Detection | Ultralytics YOLO11m | export TensorRT in Fase 2 per +40% |
| Glue detection | `supervision` | slicer, annotatori, formato Detections |
| Tracking | `boxmot` (BoT-SORT) | standalone, più configurabile del tracker integrato in Ultralytics |
| Embedding crop | SigLIP via `open_clip` | |
| Riduzione + cluster | `umap-learn`, scikit-learn | |
| Calibrazione campo | modello keypoint (PnLCalib o equivalente) + OpenCV `findHomography` RANSAC | |
| Orchestrazione | **Hamilton** + `h_polars` | |
| Classificatore inquadrature | VLM via API in Fase 1 → distillato in LightGBM se serve | |

**Assistente** <span style="color:#5AA9E6">Dev B</span>

| | Scelta | Note |
|---|---|---|
| Orchestrazione | **Apache Burr** | persistenza su Postgres |
| LLM | astrazione propria su Anthropic / OpenAI / Google SDK | ~150 righe, vedi 5.3 |
| Structured output | nativo del provider + Pydantic | |
| Query | DSL Pydantic → compilatore SQL | sezione 5.2 |
| DB | SQLAlchemy 2 (core, non ORM) + Alembic + `psycopg` 3 | |
| Vettori | `pgvector` | |
| API | FastAPI + `sse-starlette` | |
| Tracing | Langfuse SDK | |
| UI | Next.js 15, `hls.js`, TanStack Query | |

**Dove entrerebbe Rust.** Non nelle Fasi 1-3: Polars *è* Rust, e vi dà il beneficio senza scriverlo. Il posto dove guadagna il suo spazio è la Fase 4: il buffer di ingestione live — ricevere il flusso, tagliare finestre sovrapposte, servire frame al worker con backpressure — è un servizio di I/O ad alta frequenza dove Python è il collo di bottiglia. Se volete un pretesto per usarlo prima, un'estensione PyO3 per l'assegnazione del possesso (loop su milioni di righe con logica non vettorizzabile) è il candidato, ma provate prima con le espressioni Polars: nel 90% dei casi bastano.

---

## 3. Storage layer

### 3.1 Tre sistemi, tre ragioni

```
OBJECT STORAGE (MinIO → S3)          POSTGRES + PGVECTOR            HAMILTON CACHE
─────────────────────────            ───────────────────            ──────────────
video/{match_id}/source.mp4          matches                        risultati intermedi
video/{match_id}/hls/*.ts, .m3u8     video_segments                 dei nodi, per hash
tracks/match_id=X/pv=Y/*.parquet     team_orientation               di input + codice
detections/match_id=X/pv=Y/*.parquet possessions
homography/match_id=X/pv=Y/*.parquet events                         disco locale in dev,
weights/{model}/{sha}.pt             team_metrics                   S3 in prod
                                     event_embeddings (vector)
                                     feedback
                                     eval_runs, eval_cases
                                     burr_state
```

**Perché il tracking non va in Postgres**: 800k righe per partita × 20 partite = 16M righe in un mese. Postgres le regge, ma ogni query analitica scansiona tutto. Parquet partizionato con Polars lazy legge 60 MB in 200 ms. E non serve mai interrogare il tracking per riga singola.

**Perché gli eventi non vanno in Parquet**: sono poche migliaia per partita, devono essere interrogabili con filtri arbitrari, aggiornabili (`status` in Fase 4), e joinabili con feedback e metadati. È lavoro da database relazionale.

### 3.2 Partizionamento Parquet

```
tracks/
  match_id=m_2026_09_12_nap_juv/
    pipeline_version=a3f9c1/
      part-0.parquet     # frame 0–9999
      part-1.parquet     # frame 10000–19999
```

Hive-style, così Polars fa predicate pushdown su `match_id` e `pipeline_version` senza leggere i file. Una nuova versione della pipeline scrive in una nuova partizione: **i vecchi risultati non vengono sovrascritti**, e potete confrontare le versioni.

Schema Parquet dei track finali:

```
frame        u32
t_video      f32       secondi dall'inizio del file
half         u8
match_clock  f32       secondi di gioco, dal kickoff del tempo
track_id     u32
cls          u8        0 player · 1 gk · 2 referee · 3 ball
team         u8        0 A · 1 B · 255 n/a
x_img, y_img f32
x_pitch      f32       metri, orientamento normalizzato
y_pitch      f32
conf         f32
h_ok         bool      omografia accettata su questo frame
```

### 3.3 Postgres: le tabelle con i campi aggiunti

```sql
CREATE TABLE matches (
  id            text PRIMARY KEY,
  competition   text, date date,
  home_team     text, away_team   text,
  video_uri     text, hls_uri     text,
  duration_s    real, fps         real,
  camera_type   text CHECK (camera_type IN ('broadcast','tactical_fixed')),
  -- allineamento orologio
  half1_kickoff_s real, half1_end_s real,
  half2_kickoff_s real, half2_end_s real,
  status        text, pipeline_version text
);

CREATE TABLE team_orientation (
  match_id text REFERENCES matches, team smallint, half smallint,
  attack_direction smallint CHECK (attack_direction IN (-1, 1)),
  PRIMARY KEY (match_id, team, half)
);

CREATE TABLE video_segments (
  match_id text REFERENCES matches,
  t_start real, t_end real,
  view_type text,             -- tactical | replay | closeup | crowd | graphic
  usable boolean,
  half smallint, clock_start real, clock_end real
);

CREATE TABLE events (
  id          text PRIMARY KEY,
  match_id    text REFERENCES matches,
  type        text NOT NULL,
  team        smallint,
  t_video     real NOT NULL,
  t_end       real,
  half        smallint, match_clock real,
  x_pitch     real, y_pitch real,
  attrs       jsonb,
  confidence  real,
  source      text,           -- detector | derived | manual
  status      text DEFAULT 'confirmed',   -- provisional | confirmed | retracted
  revision    int  DEFAULT 1,
  pipeline_version text
);
CREATE INDEX ON events (match_id, type, half);
CREATE INDEX ON events (match_id, t_video);

CREATE TABLE team_metrics (
  match_id text, team smallint, half smallint,
  window_start real, window_end real,
  metric text, value real,
  coverage real,              -- frazione di frame osservabili nella finestra
  pipeline_version text
);

CREATE TABLE event_embeddings (
  event_id text PRIMARY KEY REFERENCES events,
  embedding vector(768)
);

CREATE TABLE feedback (
  id serial PRIMARY KEY, ts timestamptz DEFAULT now(),
  conversation_id text, turn int,
  query_text text, structured_query jsonb,
  returned_event_ids text[],
  rating smallint,            -- -1 | +1
  note text
);
```

`feedback` è la tabella da cui cresce l'eval set: ogni pollice giù è un caso candidato.

### 3.4 Cache di Hamilton

Chiave = hash(codice del nodo + input). Cambiate `detect_corner`, e Hamilton ricalcola `events` e `team_metrics` leggendo `pitch_tracks` dalla cache, senza toccare la GPU. In dev su disco locale (`~/.hamilton_cache`), in prod su S3. **Non è il sistema di storage**: è un'ottimizzazione, e va bene che venga svuotata.

---

## 4. Percezione: micro-step <span style="color:#E8B33C">Dev A</span>

Ogni riga è un nodo Hamilton. Colonna "stato": ciò che il nodo deve ricordare tra finestre in modalità live (vuoto = nodo puro, il caso facile).

### Fase 0 — Intake (una tantum per partita, fuori dal DAG)

| Step | Cosa | Output | Strumento |
|---|---|---|---|
| I1 | Transcodifica a fps costante, H.264, 1080p | `source.mp4` | ffmpeg |
| I2 | Segmentazione HLS, 4 s per segmento | `hls/` | ffmpeg |
| I3 | Inserimento in `matches` con metadati manuali | riga | script |
| I4 | **Allineamento orologio**: kickoff dei due tempi | 4 timestamp | manuale in Fase 1 (30 s di lavoro); OCR del cronometro in overlay in Fase 2 |
| I5 | **Orientamento**: quale squadra attacca dove, per tempo | `team_orientation` | manuale in Fase 1; derivato dalla posizione media dei portieri in Fase 2 |

I4 e I5 sono i due "buchi seri" chiusi con trenta secondi di lavoro umano per partita, prima di automatizzarli.

### DAG di percezione

| # | Nodo | Input | Output | Stato live | Note |
|---|---|---|---|---|---|
| P1 | `frames` | `video_uri`, `sample_fps` | iteratore di `(frame_idx, t, ndarray)` | posizione nel flusso | PyAV, decodifica hardware se disponibile. **Non materializza** |
| P2 | `shot_boundaries` | `frames` | `pl.DataFrame[t_start, t_end]` | ultimo istogramma | differenza di istogrammi HSV, soglia + minimo di durata |
| P3 | `shot_segments` | `shot_boundaries`, `frames` | + `view_type`, `usable` | — | un frame per segmento → VLM (Fase 1) o LightGBM (Fase 2) |
| P4 | `tactical_frames` | `frames`, `shot_segments` | iteratore filtrato | — | scarta il ~30% non tattico **prima** della GPU |
| P5 | `detections_full` | `tactical_frames`, `detector` | `pl.DataFrame[frame, cls, x1..y2, conf]` | — | YOLO @ 1280, batch 8, fp16 |
| P6 | `detections_ball` | `tactical_frames`, `detector` | idem, solo cls 3 | ultima posizione palla | tile 3×2 a risoluzione nativa, solo nell'intorno dell'ultima posizione nota se disponibile |
| P7 | `detections` | P5, P6 | unione, NMS sulla palla | — | |
| P8 | `tracks_raw` | `detections`, `tracker_cfg` | + `track_id` | **stato del tracker** | BoT-SORT con GMC attiva. Il nodo più stateful |
| P9 | `player_crops` | `tracks_raw`, `tactical_frames` | batch di crop 128×256 | — | solo cls 0, campionati: 1 crop ogni 5 frame per track |
| P10 | `team_labels` | `player_crops`, `siglip` | `pl.DataFrame[track_id, team]` | modello KMeans fittato | SigLIP → UMAP(2) → KMeans(2) su 2000 crop, poi voto di maggioranza per `track_id` |
| P11 | `pitch_keypoints` | `tactical_frames`, `kp_model` | `pl.DataFrame[frame, kp_id, x, y, conf]` | — | ~30 keypoint canonici |
| P12 | `homography_raw` | `pitch_keypoints` | `pl.DataFrame[frame, H(9), n_inliers, err]` | — | `findHomography` RANSAC, ≥ 4 punti |
| P13 | `homography` | `homography_raw` | + `ok`, H lisciata | ultime N matrici | gate: `n_inliers ≥ 6 ∧ err < 1.5 m`; smoothing con mediana mobile (batch) o EMA (live) |
| P14 | `homography_acceptance_rate` | `homography` | `float` | — | `@check_output(range=(0,1))`; log warning sotto 0.6 |
| P15 | `pitch_tracks` | `tracks_raw`, `team_labels`, `homography`, `team_orientation`, `clock_alignment` | schema §3.2 | — | proietta, filtra `h_ok`, normalizza orientamento, aggiunge `half` e `match_clock` |
| P16 | `max_player_speed_kmh` | `pitch_tracks` | `float` | — | `@check_output(range=(0,40))` — sopra 40 l'omografia è rotta |
| P17 | `pitch_tracks_parquet` | `pitch_tracks` | path | — | materializer, partizione Hive |

**Il frame loop vive in P1 e P4** come generatori. I nodi P5-P6 consumano il generatore a batch. Hamilton non vede mai un nodo per frame.

**Convenzioni**: cls 0-3 come `IntEnum` in `core`; coordinate immagine in pixel del frame 1080p; coordinate campo in metri con origine nell'angolo in basso a sinistra del campo *nel sistema normalizzato* (squadra analizzata attacca verso +x).

### DAG di derivazione

| # | Nodo | Input | Output | Note |
|---|---|---|---|---|
| D1 | `ball_track` | `pitch_tracks` | serie `[t, x, y, conf, interpolated]` | Kalman + interpolazione lineare su gap ≤ 1 s; flag `interpolated` |
| D2 | `ball_carrier` | `pitch_tracks`, `ball_track` | `[t, track_id, team, dist]` | **`join_asof`** palla→giocatore più vicino entro 2 m |
| D3 | `possessions` | `ball_carrier` | `[t_start, t_end, team, ...]` | run-length su `team`, con isteresi (≥ 3 frame per cambiare) |
| D4 | `possessions_fallback` | `pitch_tracks` | idem | **quando la palla manca**: direzione media del movimento delle due squadre. Confidence 0.4 |
| D5 | `possessions_merged` | D3, D4 | idem | D3 dove disponibile, D4 nei buchi |
| D6 | `team_shape` | `pitch_tracks` | per frame: centroide, ampiezza, profondità, linea difensiva per squadra | `over("frame","team")`; **solo frame con ≥ 7 giocatori visibili per squadra** |
| D7 | `events_geometric` | D5, D6, `ball_track`, registry | `list[Event]` | corner, rimessa, fuori campo, cambio possesso, kickoff — regole pure |
| D8 | `events_statistical` | D5, D6, `ball_track`, registry | `list[Event]` | cross, tiro, passaggio ultimo terzo, transizione, pressing — regole con soglie |
| D9 | `events` | D7, D8 | `pl.DataFrame` schema `events` | dedup temporale (stesso tipo entro 2 s), `confidence` |
| D10 | `team_metrics` | D6, D5 | finestre da 5 min | media per finestra + **`coverage`** = frazione di frame con ≥ 7 visibili |
| D11 | `event_embeddings` | `events`, `pitch_tracks` | vettori 768 | testo strutturato dell'evento + contesto spaziale → embedding |
| D12 | `persist` | D9, D10, D11 | — | upsert Postgres via `pipeline_version` |

**Ordine di implementazione**: D1 → D2 → D3 → D7 in Fase 2 prima settimana (già utile per l'assistente), poi D6 e D8, poi D4 e D10.

### Il registry dei detector (dalla discussione precedente)

```python
@detector("corner", CornerParams)
def detect_corner(ball: pl.DataFrame, poss: pl.DataFrame,
                  p: CornerParams) -> list[Event]:
    still = (ball
        .with_columns(pl.col("x").diff().abs().rolling_sum(p.min_still_frames).alias("dx"))
        .filter(pl.col("dx") < 0.5))
    near_flag = still.filter(
        ((pl.col("x") < p.radius_m) | (pl.col("x") > 105 - p.radius_m)) &
        ((pl.col("y") < p.radius_m) | (pl.col("y") > 68 - p.radius_m)))
    return [Event(type="corner", t_video=r["t"], confidence=0.9, ...)
            for r in near_flag.iter_rows(named=True)]
```

Puro, testabile con un dataframe finto, e la config seleziona soglie non struttura.

---

## 5. Assistente: micro-step <span style="color:#5AA9E6">Dev B</span>

### 5.1 La macchina a stati Burr

```
                    ┌──────────────────┐
     ┌──────────────│ ask_clarification│◄───────────┐
     │              └──────────────────┘            │ needs_clarification
     ▼                                              │
  [turn end]                                ┌───────┴────────┐
                                            │classify_intent │
                                            └───────┬────────┘
                                                    │
                                            ┌───────▼────────┐
                                            │resolve_context │  deterministico + riscrittura
                                            └───────┬────────┘
                                                    │
                          has_errors ∧ retries<2    │
                         ┌──────────────────┐      │
                         │                  ▼      ▼
                         │          ┌───────────────┐
                         └──────────│  build_query  │
                                    └───────┬───────┘
                                            │ valid
                                    ┌───────▼───────┐
                                    │ execute_query │  deterministico
                                    └───────┬───────┘
                                            │
                                    ┌───────▼───────┐
                          ┌────────►│compose_answer │  streaming
                          │         └───────┬───────┘
                          │                 │
             not_grounded │         ┌───────▼────────┐
             ∧ retries<1  └─────────│verify_grounding│  deterministico
                                    └───────┬────────┘
                                            │
                                    ┌───────▼───────┐
                                    │    respond    │  → AnswerPayload
                                    └───────────────┘
```

**Stato** (chiavi come costanti):

```python
class S:
    MESSAGES = "messages"  # storia, reducer append
    MATCH_CONTEXT = "match_context"  # match_id attivi, squadra di riferimento
    QUERY_TEXT = "query_text"
    INTENT = "intent"
    NEEDS_CLARIF = "needs_clarification"
    CLARIF_Q = "clarification_question"
    RESOLVED_QUERY = "resolved_query"  # testo riscritto, riferimenti risolti
    STRUCTURED = "structured_query"  # Query (Pydantic)
    VALIDATION_ERR = "validation_errors"
    QUERY_RETRIES = "query_retries"
    RESULTS = "results"  # list[EventRow] | MetricRows
    COVERAGE = "coverage"
    ANSWER = "answer"
    CITATIONS = "citations"  # list[event_id]
    GROUNDED = "grounded"
    GROUND_RETRIES = "ground_retries"
    PAYLOAD = "payload"  # AnswerPayload
```

| Azione | reads | writes | LLM? | Cosa fa |
|---|---|---|---|---|
| `classify_intent` | QUERY_TEXT, MESSAGES, MATCH_CONTEXT | INTENT, NEEDS_CLARIF, CLARIF_Q | sì, piccolo | structured output: `{intent, needs_clarification, question}`. Intent ∈ {find_moments, compute_metric, compare, report, chitchat} |
| `ask_clarification` | CLARIF_Q | MESSAGES | no | termina il turno con la domanda |
| `resolve_context` | QUERY_TEXT, MESSAGES, MATCH_CONTEXT | RESOLVED_QUERY, MATCH_CONTEXT | sì, solo se follow-up | (1) fuzzy-match dei nomi squadra su `matches`; (2) "l'ultima partita" → match_id; (3) se la storia non è vuota, riscrittura in query autonoma |
| `build_query` | RESOLVED_QUERY, INTENT, VALIDATION_ERR, QUERY_RETRIES | STRUCTURED, VALIDATION_ERR, QUERY_RETRIES | sì | structured output sul discriminated union `Query`. Su errore Pydantic: messaggio d'errore in contesto e retry (max 2) |
| `execute_query` | STRUCTURED | RESULTS, COVERAGE | no | `compile(query) → SQL`, esegue, attacca coverage |
| `compose_answer` | RESOLVED_QUERY, RESULTS, COVERAGE, GROUND_RETRIES | ANSWER, CITATIONS | sì, **streaming** | risposta in italiano; ogni claim cita `[evt_xxx]`; se coverage < 0.5 lo dice |
| `verify_grounding` | CITATIONS, RESULTS, GROUND_RETRIES | GROUNDED, GROUND_RETRIES | no | `set(citations) ⊆ {r.id for r in results}` |
| `respond` | ANSWER, CITATIONS, RESULTS, GROUNDED | PAYLOAD, MESSAGES | no | costruisce `AnswerPayload`; se non grounded dopo retry, risponde con i soli risultati senza prosa |

Persistenza su Postgres con `conversation_id` come chiave; ogni turno è un'applicazione Burr ripresa dallo stato precedente.

### 5.2 Il DSL di query

È il pezzo che mancava. Il principio: **l'LLM sceglie tra opzioni chiuse, non scrive.**

```python
from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field

# generato dal registry dei detector — l'LLM può chiedere solo ciò che esiste
EventType = Literal[
    "corner",
    "throw_in",
    "goal_kick",
    "shot",
    "cross",
    "pass_final_third",
    "turnover",
    "counter_attack",
    "press_trigger",
    "kickoff",
]

MetricName = Literal[
    "defensive_line_height",
    "team_width",
    "compactness",
    "possession_share",
    "recoveries_by_zone",
    "ppda_proxy",
]

Zone = Literal[
    "defensive_third", "middle_third", "final_third", "left_flank", "center", "right_flank", "box"
]


class TimeWindow(BaseModel):
    half: Literal[1, 2] | None = None
    clock_from_min: int | None = Field(None, ge=0, le=130)
    clock_to_min: int | None = Field(None, ge=0, le=130)
    last_n_min: int | None = Field(None, ge=1, le=90)  # per il live
    model_config = {"extra": "forbid"}


class FindMoments(BaseModel):
    intent: Literal["find_moments"]
    match_ids: list[str] = Field(min_length=1)
    event_types: list[EventType] = Field(min_length=1)
    team: Literal["A", "B", "both"] = "both"
    zone: Zone | None = None
    time: TimeWindow | None = None
    min_confidence: float = Field(0.5, ge=0, le=1)
    limit: int = Field(20, le=100)
    model_config = {"extra": "forbid"}


class ComputeMetric(BaseModel):
    intent: Literal["compute_metric"]
    match_ids: list[str]
    metric: MetricName
    team: Literal["A", "B"]
    time: TimeWindow | None = None
    group_by: Literal["match", "half", "window"] = "match"
    model_config = {"extra": "forbid"}


class CompareMatches(BaseModel):
    intent: Literal["compare"]
    match_ids: list[str] = Field(min_length=2)
    metric: MetricName
    team: Literal["A", "B"]
    model_config = {"extra": "forbid"}


class SimilarMoments(BaseModel):
    intent: Literal["similar"]
    anchor_event_id: str
    match_ids: list[str] | None = None
    limit: int = 10
    model_config = {"extra": "forbid"}


Query = Annotated[
    Union[FindMoments, ComputeMetric, CompareMatches, SimilarMoments],
    Field(discriminator="intent"),
]
```

**Il compilatore** — una funzione per variante, SQL parametrizzato, mai stringhe dall'LLM:

```python
def compile_find_moments(q: FindMoments) -> tuple[str, dict]:
    sql = """
      SELECT id, match_id, type, team, t_video, half, match_clock,
             x_pitch, y_pitch, confidence
      FROM events
      WHERE match_id = ANY(:match_ids) AND type = ANY(:types)
        AND confidence >= :minc AND status <> 'retracted'
    """
    params = {"match_ids": q.match_ids, "types": q.event_types, "minc": q.min_confidence}
    if q.team != "both":
        sql += " AND team = :team"
        params["team"] = 0 if q.team == "A" else 1
    if q.zone:
        sql += f" AND {ZONE_PREDICATES[q.zone]}"  # predicati fissi, non input
    if q.time:
        sql, params = apply_time_window(sql, params, q.time)
    sql += " ORDER BY t_video LIMIT :limit"
    params["limit"] = q.limit
    return sql, params
```

**Le tre proprietà di sicurezza**: la sintassi SQL è nel compilatore, non nell'LLM; i valori passano come parametri bindati; i vocabolari sono `Literal` generati dal codice, quindi un evento che non esiste è un errore Pydantic prima di toccare il database.

**`EventType` si genera dal registry** a import time:

```python
EventType = Literal[tuple(sorted(DETECTORS))]  # type: ignore[valid-type]
```

Aggiungete un detector, e l'assistente lo sa senza toccare nient'altro.

### 5.3 L'astrazione sul provider

```python
class LLM(Protocol):
    async def structured(self, messages, schema: type[T], *, model: str) -> T: ...
    async def stream(self, messages, *, model: str) -> AsyncIterator[str]: ...


# routing per nodo, da config
LLM_ROUTES = {
    "classify_intent": "haiku",  # economico
    "resolve_context": "haiku",
    "build_query": "sonnet",  # deve essere preciso
    "compose_answer": "sonnet",
    "judge": "opus",  # solo in eval, offline
}
```

Tre implementazioni concrete (Anthropic, OpenAI, Google), ognuna ~50 righe, che espongono lo structured output nativo del provider. Il prompt caching lo attivate sul prefisso stabile: schema del DSL + descrizione degli eventi + istruzioni.

### 5.4 Il payload verso il frontend

```python
class ClipRef(BaseModel):
    event_id: str
    match_id: str
    t_video: float  # dove saltare
    t_end: float | None
    match_clock: str  # "52'18\"" per la UI
    type: EventType
    confidence: float


class AnswerPayload(BaseModel):
    text: str  # markdown con [evt_xxx] inline
    clips: list[ClipRef]
    coverage: float | None
    grounded: bool
    structured_query: Query  # per debug e per il feedback
```

Il frontend rende i `[evt_xxx]` nel testo come chip cliccabili, mette i `clips` come marker sulla timeline, e al click fa `video.currentTime = t_video`. Il feedback (👍/👎) salva `structured_query` e `clips` in `feedback`.

### 5.5 API

```
POST /matches                          upload + intake
GET  /matches/{id}                     metadati + stato pipeline
GET  /matches/{id}/hls/playlist.m3u8   proxy allo storage
GET  /matches/{id}/timeline            eventi per la barra
POST /ask                              body: {conversation_id, match_ids, text}
                                       → SSE: token | clips | done
POST /feedback
```

Lo streaming SSE emette tre tipi di evento: `token` (testo di `compose_answer`), `clips` (una volta, dopo `verify_grounding`), `done` con il payload completo.

---

## 6. Configurazione

```
config/
  base.yaml            # default
  broadcast.yaml       # camera: broadcast, soglie di omografia, tile palla
  fixed.yaml           # camera: fixed
  live.yaml            # mode: live, fps 5, modello s, no tile
  detectors/
    serie_a.yaml       # soglie dei detector
  llm.yaml             # routing per nodo, provider, cache
```

Caricati con Pydantic Settings, uniti per precedenza, **validati contro schemi Pydantic in un test che gira su ogni file**. Il grafo resta in Python; la config seleziona e parametrizza.

---

## 7. Sequenza di implementazione, prima settimana di ciascuno

**Dev A, Fase 1 settimana 1**: I1-I3 + P1 + P5 su una partita, con `pitch_tracks_parquet` che scrive detection grezze senza omografia. Obiettivo: il DAG gira end-to-end su 5 minuti di video, anche se i nodi intermedi sono stub. Poi si riempiono.

**Dev B, Fase 1 settimana 1**: DSL + compilatore + `execute_query` su timeline sintetica, testati con pytest, **senza LLM**. Poi `build_query` con un provider. Il grafo Burr completo alla fine della settimana 2.

L'ordine è deliberato: prima la parte deterministica, poi quella probabilistica. Se il compilatore è testato, ogni errore dopo è dell'LLM, e si vede.
