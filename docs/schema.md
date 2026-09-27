# Schema della timeline — il contratto

**Versione:** 1.0 · **Stato:** in review (P0.3+S0.2). Diventa *congelato* quando la PR è approvata da entrambi i dev.

Questo documento è **la fonte di verità** per tutto ciò che percezione e assistente si scambiano: tabelle Postgres, dataset Parquet, enum, sistemi di coordinate e di tempo. `architecture.md` §3 e `technical-design.md` §3 ne danno una sintesi e rimandano qui. Se c'è un conflitto, vince questo file.

**Come si cambia.** Ogni modifica è una PR con due reviewer, con migrazione Alembic e con questo file aggiornato nello stesso commit (CLAUDE.md). La tabella delle modifiche è in fondo.

---

## 1. Principi

1. **Due sistemi, un contratto** (ADR-002). La percezione scrive la timeline; l'assistente la legge. Non si chiamano mai: passano solo da Postgres e dal bucket.
2. **`confidence`, `coverage`, `pipeline_version`** sono `NOT NULL` ovunque compaiono (ADR-010). Un valore stimato senza la sua affidabilità non entra nel database.
3. **Mai sovrascrivere una versione.** Una nuova `pipeline_version` aggiunge righe e partizioni, non sostituisce quelle vecchie (§6).
4. **`track_id` non è un giocatore.** È un identificativo di traccia valido solo dentro una partita e una versione, e cambia quando il giocatore esce dall'inquadratura. Nessuna colonna Postgres contiene `track_id`, numeri di maglia o identità di giocatore. Nessuna logica a valle può dipendere dall'identità a lungo termine.
5. **Vocabolari chiusi.** Ogni colonna categoriale corrisponde a un enum in `packages/core`. In Postgres è `text` con un `CHECK` generato dallo stesso enum (§3).

---

## 2. Tempo e coordinate

### 2.1 Tempo

Ci sono due orologi. Il nome della colonna dice sempre quale dei due usa.

| Dominio | Colonne | Unità | Origine |
|---|---|---|---|
| **Video** | `t_video`, `t_start`, `t_end`, `duration_s`, `half*_kickoff_s`, `half*_end_s` | secondi, `real` | primo frame di `source.mp4` (il file transcodificato dall'intake, non l'originale) |
| **Gioco** | `match_clock`, `clock_start`, `clock_end`, `window_start`, `window_end` | secondi, `real` | kickoff **del tempo** indicato da `half` |

Regole:

- `match_clock = t_video − halfN_kickoff_s`, con N = `half`. L'orologio **riparte da 0 a ogni tempo** e non si ferma: include il recupero.
- Una colonna di gioco non ha senso senza `half`. Dove c'è `match_clock` c'è sempre `half`.
- `half` vale 1 o 2. I supplementari sono fuori scope in v1.
- **Minuto per la UI e per il DSL:** `minuto = floor(match_clock / 60) + (0 se half = 1, 45 se half = 2)`. Oltre il 45' del primo tempo e il 90' del secondo si mostra `45+k'` e `90+k'`. Tra 45 e 50 il minuto è ambiguo (recupero del primo tempo o inizio del secondo): se una finestra del DSL non specifica `half`, il compilatore la applica a entrambi i tempi.
- Tutti i tempi sono `real` (float4). A 6000 s la risoluzione è di circa 0,5 ms, molto sotto un frame.

### 2.2 Coordinate immagine

- Pixel del frame **1920×1080**. L'intake garantisce che ogni `source.mp4` sia in 1080p (I1).
- Origine nell'angolo in alto a sinistra, x verso destra, y verso il basso. Valori `real`, subpixel ammessi.
- Il punto di una traccia (`x_img`, `y_img`) è il **centro del lato inferiore del box** (i piedi) per le persone, e il **centro del box** per la palla. È il punto che viene proiettato sul campo.

### 2.3 Coordinate campo

- **Campo canonico 105 × 68 m** (`PITCH_L`, `PITCH_W` in `core`). L'omografia proietta sul modello canonico qualunque siano le dimensioni reali del campo, e le distanze vanno lette in metri canonici. In v1 `matches` non ha le dimensioni reali (§8, D5).
- Metri, `real`. Origine nell'angolo in basso a sinistra, **x lungo la linea laterale** (0 → 105), **y lungo la linea di porta** (0 → 68).
- **Sistema normalizzato:** la squadra A (§3.2) attacca **sempre verso +x**, in entrambi i tempi. Tutte le coordinate campo in Parquet e in Postgres sono normalizzate. Coordinate non normalizzate non escono mai dalla percezione.
- **La normalizzazione è una rotazione di 180°, non uno specchio:** nei tempi in cui A attacca verso −x nel sistema grezzo della camera, `x' = 105 − x` e `y' = 68 − y`. La rotazione conserva destra e sinistra, quindi le fasce restano corrette. Uno specchio le invertirebbe.
- Il sistema grezzo è quello della camera principale: y = 0 è la linea laterale più vicina alla camera, x = 0 la linea di porta alla sua sinistra. `team_orientation.attack_direction` è espresso in questo sistema.
- Punti notevoli, già normalizzati: centro (52.5, 34); porta di A (x = 0) e porta attaccata da A (x = 105), entrambe con il centro a y = 34; area di rigore attaccata da A: `x ≥ 88.5 ∧ 13.84 ≤ y ≤ 54.16`.
- Chi guarda nella direzione d'attacco di A ha la **sinistra verso +y**.
- Ammessi valori leggermente fuori dal campo (rimesse, giocatori oltre la linea): `x ∈ [−5, 110]`, `y ∈ [−5, 73]`. Oltre questi limiti l'omografia è rotta e il punto viene scartato.

### 2.4 Zone

Le zone sono **relative alla squadra della riga**: *final_third* è il terzo che quella squadra attacca. Per una riga di A si usano le coordinate così come sono; per una riga di B si ruota prima il punto (`x' = 105 − x`, `y' = 68 − y`) e poi si applica la stessa tabella. Se `team` è NULL, vale la prospettiva di A.

| `Zone` | Predicato (prospettiva della squadra, già ruotato) |
|---|---|
| `defensive_third` | `x < 35` |
| `middle_third` | `35 ≤ x < 70` |
| `final_third` | `x ≥ 70` |
| `left_flank` | `y ≥ 45.33` |
| `center` | `22.67 ≤ y < 45.33` |
| `right_flank` | `y < 22.67` |
| `box` | `x ≥ 88.5 ∧ 13.84 ≤ y ≤ 54.16` |

Le zone **si sovrappongono** (un punto è in un terzo *e* in una fascia), quindi non sono una partizione e non si salvano in una colonna. Si calcolano dalle coordinate con predicati fissi, nel compilatore del DSL (`ZONE_PREDICATES`). Una riga senza coordinate non appartiene a nessuna zona.

---

## 3. Enum

Vivono tutti in `packages/core/src/core/models/enums.py`. In Postgres ogni colonna categoriale è `text` (o `smallint` per gli `IntEnum`) con un `CHECK` generato **dall'enum stesso** nella migrazione, così i valori non si copiano a mano. Aggiungere un valore vuol dire modificare il contratto: enum + migrazione + questo file.

### 3.1 Percezione

```python
class Cls(IntEnum):  # tracks.cls
    PLAYER = 0
    GOALKEEPER = 1
    REFEREE = 2
    BALL = 3


class ViewType(StrEnum):  # video_segments.view_type
    TACTICAL = "tactical"  # campo largo, omografia possibile
    REPLAY = "replay"
    CLOSEUP = "closeup"
    CROWD = "crowd"
    GRAPHIC = "graphic"  # grafica a tutto schermo: formazioni, statistiche
    UNKNOWN = "unknown"  # il classificatore non ha deciso


class CameraType(StrEnum):  # matches.camera_type, seleziona @config.when
    BROADCAST = "broadcast"
    TACTICAL_FIXED = "tactical_fixed"
```

### 3.2 Squadre

```python
class Team(IntEnum):  # team in Parquet e in Postgres
    A = 0  # la squadra analizzata, vedi matches.team_a_side
    B = 1
```

"Nessuna squadra" (palla, arbitro, traccia non ancora assegnata, evento non attribuibile) si scrive **NULL**, sia in Parquet sia in Postgres. Il valore sentinella 255 non si usa (§8, D3).

A e B non sono casa e trasferta: `matches.team_a_side` dice se A è la squadra di casa o quella in trasferta. Per confrontare più partite della stessa squadra, la si mette come A in ognuna.

### 3.3 Timeline

```python
class EventType(StrEnum):  # events.type — vedi ADR-013
    CORNER = "corner"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    KICKOFF = "kickoff"
    TURNOVER = "turnover"
    SHOT = "shot"
    CROSS = "cross"
    PASS_FINAL_THIRD = "pass_final_third"
    COUNTER_ATTACK = "counter_attack"
    PRESS_TRIGGER = "press_trigger"


class MetricName(StrEnum):  # team_metrics.metric
    DEFENSIVE_LINE_HEIGHT = "defensive_line_height"
    TEAM_WIDTH = "team_width"
    COMPACTNESS = "compactness"
    POSSESSION_SHARE = "possession_share"
    PPDA_PROXY = "ppda_proxy"


class Zone(StrEnum):  # solo DSL, mai in colonna — §2.4
    DEFENSIVE_THIRD = "defensive_third"
    MIDDLE_THIRD = "middle_third"
    FINAL_THIRD = "final_third"
    LEFT_FLANK = "left_flank"
    CENTER = "center"
    RIGHT_FLANK = "right_flank"
    BOX = "box"


class EventSource(StrEnum):  # events.source
    DETECTOR = "detector"  # emesso da un detector del registry, sul tracking
    DERIVED = "derived"  # combinazione di altri eventi o possessi
    MANUAL = "manual"  # inserito o corretto da una persona


class EventStatus(StrEnum):  # events.status
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"  # unico valore ammesso fino a M4
    RETRACTED = "retracted"


class PossessionSource(StrEnum):  # possessions.source
    BALL = "ball"  # D3: dalla palla e dal portatore
    FALLBACK = "fallback"  # D4: palla assente, movimento collettivo


class PossessionOutcome(StrEnum):  # possessions.outcome
    SHOT = "shot"
    TURNOVER = "turnover"  # palla persa in gioco
    OUT_OF_PLAY = "out_of_play"
    END_OF_HALF = "end_of_half"
    UNKNOWN = "unknown"
```

La semantica di ogni `EventType` è in §5.5 e le unità di ogni `MetricName` in §5.6.

Il DSL (S0.5) importa `EventType`, `MetricName` e `Zone` da `core` e ne ricava i `Literal`. Il registry dei detector (P2.4, M2) si valida contro `EventType`, non il contrario. La decisione e le sue conseguenze sono in **ADR-013**.

### 3.4 Operativi

```python
class MatchStatus(StrEnum):  # matches.status
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class JobKind(StrEnum):  # jobs.kind
    INGEST = "ingest"
    REPROCESS = "reprocess"


class JobStatus(StrEnum):  # jobs.status
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EvalKind(StrEnum):  # eval_cases.kind
    PERCEPTION = "perception"
    ASSISTANT = "assistant"


class EvalCaseStatus(StrEnum):  # eval_cases.status
    CANDIDATE = "candidate"  # proposto, ad esempio da un feedback negativo
    ACTIVE = "active"
    RETIRED = "retired"


class TeamSide(StrEnum):  # matches.team_a_side
    HOME = "home"
    AWAY = "away"
```

---

## 4. Object storage

```
video/{match_id}/source.mp4                          intake    → worker
video/{match_id}/hls/playlist.m3u8, seg-*.ts         intake    → web
tracks/match_id={id}/pipeline_version={pv}/part-N.parquet   worker → derivazione, QA
weights/{model}/{sha}.pt                             training  → worker
```

Solo `video/` e `tracks/` fanno parte del contratto. `detections/` e `homography/` (technical-design §3.1) sono intermedi interni alla percezione: nessun altro li legge, e possono cambiare senza passare da questo documento.

### 4.1 Parquet `tracks`

Una riga per ogni detection tracciata su un frame tattico. Partizionamento Hive su `match_id` e `pipeline_version`, circa 10.000 frame per file. Una partizione, una volta scritta, è **immutabile**.

| Colonna | Tipo | Null | Significato |
|---|---|---|---|
| `frame` | u32 | no | indice del frame in `source.mp4` |
| `t_video` | f32 | no | secondi, dominio video |
| `half` | u8 | no | 1 · 2 |
| `match_clock` | f32 | no | secondi dal kickoff del tempo |
| `track_id` | u32 | no | unico **solo** dentro (`match_id`, `pipeline_version`). **Non è un giocatore** |
| `cls` | u8 | no | `Cls` |
| `team` | u8 | sì | `Team`; NULL per palla, arbitro e tracce non assegnate |
| `x_img`, `y_img` | f32 | no | pixel 1080p, punto definito in §2.2 |
| `x_pitch`, `y_pitch` | f32 | sì | metri normalizzati; NULL se e solo se `h_ok = false` |
| `conf` | f32 | no | confidenza della detection, tra 0 e 1 |
| `h_ok` | bool | no | omografia accettata su questo frame (gate di P13) |

Invarianti, controllati con `@check_output` su P15/P17:

- Nel file ci sono solo i frame dentro un tempo: niente pre-partita, intervallo o post-partita.
- (`frame`, `track_id`) è unica.
- `h_ok = false` ⇒ `x_pitch` e `y_pitch` sono NULL. Si tengono comunque le coordinate immagine, perché servono al QA e al calcolo della coverage.
- La coppia `x_pitch`, `y_pitch` resta nei limiti di §2.3.

**Scrive:** worker (P17). **Legge:** DAG di derivazione, script di QA radar. L'assistente non legge mai il tracking.

---

## 5. Postgres

### 5.0 Convenzioni comuni

- Le colonne categoriali sono `text` con `CHECK (col IN (…))` generato dall'enum. `team` e `half` sono `smallint` con `CHECK`.
- Tutte le tabelle legate a una partita hanno `match_id text NOT NULL REFERENCES matches(id) ON DELETE CASCADE`.
- Una `confidence` o una `coverage` è sempre `real NOT NULL CHECK (x BETWEEN 0 AND 1)`.
- Una `pipeline_version` è sempre `text NOT NULL CHECK (pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$')`. Il contenuto lo decide il worker (sha del commit più hash di config e pesi). Il contratto garantisce una cosa sola: righe con lo stesso valore sono state prodotte dallo stesso codice, con la stessa config e gli stessi pesi. I dati sintetici usano `synth-v1`.
- Gli id testuali hanno un prefisso: `m_` per le partite, `evt_` per gli eventi, `pos_` per i possessi.
- I timestamp di sistema sono `timestamptz`.

**Chi scrive cosa.** Ogni tabella ha **un solo** processo che la scrive in produzione. `tools/synth` scrive le stesse tabelle al posto di intake e worker, passando dai modelli e dai repo di `core`.

| Tabella | Scrive | Legge |
|---|---|---|
| `matches` | intake (P0.4), CLI di allineamento (P0.5), worker (solo `status` e `active_pipeline_version`) | worker, API, assistente, web |
| `team_orientation` | CLI di allineamento (P0.5, M1) → worker (P3.5, M3) | worker (P15) |
| `video_segments` | worker (P3 → D12) | web, API |
| `possessions` | worker (D5 → D12) | assistente, API |
| `events` | worker (D9 → D12) | assistente, API, web |
| `team_metrics` | worker (D10 → D12) | assistente, API |
| `event_embeddings` | worker (D11 → D12, M3) | assistente |
| `jobs` | intake e API (inserimento), worker (transizioni di stato) | worker |
| `pipeline_runs` | worker (adapter Hamilton, P0.9) | chi fa debug |
| `feedback` | API (`POST /feedback`) | chi cura l'eval |
| `burr_state` | persister di Burr, dentro l'API | API, Burr UI |
| `eval_cases` | chi cura l'eval, loader dell'eval | runner dell'eval (CI) |
| `eval_runs` | runner dell'eval (CI) | CI, chi cura l'eval |

L'assistente **non scrive mai** le tabelle della timeline. Il worker **non legge mai** `feedback`, `burr_state` o `eval_*`.

---

### 5.1 `matches`

Una riga per partita. Contiene le ancore dell'orologio, il tipo di camera (che seleziona la variante del DAG) e il puntatore alla versione attiva.

| Colonna | Tipo | Vincoli | Note |
|---|---|---|---|
| `id` | text | PK, `~ '^m_[a-z0-9_]{1,62}$'` | es. `m_2026_09_12_nap_juv` |
| `competition` | text | | |
| `date` | date | NOT NULL | serve a «l'ultima partita» |
| `home_team`, `away_team` | text | NOT NULL | nomi per il fuzzy match di `resolve_context` |
| `team_a_side` | text | NOT NULL, `TeamSide` | quale delle due è A |
| `video_uri` | text | NOT NULL | `s3://…/video/{id}/source.mp4` |
| `hls_uri` | text | NOT NULL | playlist `.m3u8` |
| `duration_s` | real | NOT NULL, > 0 | durata di `source.mp4` |
| `fps` | real | NOT NULL, > 0 | costante, lo garantisce I1 |
| `camera_type` | text | NOT NULL, `CameraType` | |
| `half1_kickoff_s`, `half1_end_s`, `half2_kickoff_s`, `half2_end_s` | real | NULL finché P0.5 non li scrive | dominio video. `CHECK`: o tutti NULL o tutti valorizzati, con `0 ≤ h1k < h1e ≤ h2k < h2e ≤ duration_s` |
| `status` | text | NOT NULL, `MatchStatus`, default `queued` | stato dell'ultimo job, solo informativo |
| `active_pipeline_version` | text | NULL | la versione che i lettori vedono; NULL = nessuna timeline ancora disponibile |
| `created_at` | timestamptz | NOT NULL, default `now()` | |

Vincolo: `status = 'ready'` ⇒ `active_pipeline_version IS NOT NULL` e le quattro ancore sono valorizzate.

`active_pipeline_version` è un puntatore, non un dato di provenienza: dice quale versione leggere. Per questo può essere NULL (una partita appena caricata non ha ancora una timeline) e ADR-010 non si applica. I campi di provenienza `pipeline_version` stanno sulle righe prodotte, e lì sono sempre `NOT NULL` (§8, D4).

### 5.2 `team_orientation`

Quale squadra attacca verso quale lato, per ciascun tempo, nel sistema grezzo della camera. È un **input** della percezione, non un suo output, e per questo non ha `pipeline_version`.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `match_id` | text | FK |
| `team` | smallint | NOT NULL, `Team` |
| `half` | smallint | NOT NULL, 1 · 2 |
| `attack_direction` | smallint | NOT NULL, `IN (-1, 1)`: verso +x o −x grezzo |

PK (`match_id`, `team`, `half`). Una partita orientata ha esattamente 4 righe. Invarianti, validati dal modello Pydantic che le raccoglie e non dal database: nello stesso tempo le due squadre hanno direzioni opposte; tra un tempo e l'altro la stessa squadra inverte la direzione.

P15 normalizza con la sola riga di A: se `attack_direction = −1` in un tempo, ruota le coordinate di quel tempo (§2.3).

### 5.3 `video_segments`

La partita divisa per tipo di inquadratura. Solo i segmenti `usable` alimentano omografia e metriche.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `match_id` | text | FK |
| `pipeline_version` | text | NOT NULL |
| `t_start`, `t_end` | real | NOT NULL, `t_start ≥ 0`, `t_end > t_start` |
| `view_type` | text | NOT NULL, `ViewType` |
| `usable` | boolean | NOT NULL; `CHECK (NOT usable OR view_type = 'tactical')` |
| `half` | smallint | NULL fuori dai tempi |
| `clock_start`, `clock_end` | real | NULL se e solo se `half` è NULL |

PK (`match_id`, `pipeline_version`, `t_start`). Invariante, verificato con `@check_output`: per ogni versione, i segmenti coprono `[0, duration_s]` senza sovrapporsi. Un segmento non attraversa un kickoff: P3 lo spezza lì.

### 5.4 `possessions`

Run di possesso di una squadra, con isteresi. Sono la base degli eventi e di `possession_share`.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `id` | text | PK, `pos_…` |
| `match_id` | text | FK |
| `pipeline_version` | text | NOT NULL |
| `team` | smallint | NOT NULL, `Team` |
| `t_start`, `t_end` | real | NOT NULL, `t_end > t_start` |
| `half` | smallint | NOT NULL; un possesso non attraversa l'intervallo |
| `clock_start`, `clock_end` | real | NOT NULL |
| `x_start`, `y_start`, `x_end`, `y_end` | real | NULL se la posizione della palla è ignota; le due coppie sono nulle o valorizzate insieme |
| `outcome` | text | NOT NULL, `PossessionOutcome` |
| `n_passes` | smallint | NULL se non misurabile, sempre NULL con `source = 'fallback'` |
| `source` | text | NOT NULL, `PossessionSource` |
| `confidence` | real | NOT NULL, [0, 1]; 0.4 per il fallback |

Indice: (`match_id`, `pipeline_version`, `t_start`). Invariante: per ogni (`match_id`, `pipeline_version`) i possessi non si sovrappongono. I buchi sono ammessi (palla ferma, inquadratura non tattica). Le zone di inizio e di fine si calcolano dalle coordinate con §2.4.

### 5.5 `events`

Il cuore della timeline. Poche migliaia di righe per partita, interrogabili con filtri arbitrari.

| Colonna | Tipo | Vincoli | Note |
|---|---|---|---|
| `id` | text | PK, `~ '^evt_[a-z0-9]{12}$'` | deterministico: hash di (`match_id`, `pipeline_version`, `type`, `t_video` arrotondato al centesimo). Rieseguire la stessa versione ridà gli stessi id |
| `match_id` | text | FK | |
| `pipeline_version` | text | NOT NULL | |
| `type` | text | NOT NULL, `EventType` | |
| `team` | smallint | NULL = non attribuibile | semantica per tipo nella tabella sotto |
| `t_video` | real | NOT NULL, ≥ 0 | **dove salta il player**: l'istante dell'evento, o il suo inizio se ha una durata. Il pre-roll lo aggiunge la UI, non il dato |
| `t_end` | real | NULL = evento puntuale; altrimenti ≥ `t_video` | dominio video |
| `half` | smallint | NOT NULL | |
| `match_clock` | real | NOT NULL, ≥ 0 | corrisponde a `t_video` |
| `x_pitch`, `y_pitch` | real | NULL insieme | metri normalizzati; punto per tipo nella tabella sotto |
| `attrs` | jsonb | NOT NULL, default `'{}'` | vedi sotto |
| `confidence` | real | NOT NULL, [0, 1] | |
| `source` | text | NOT NULL, `EventSource` | |
| `status` | text | NOT NULL, default `'confirmed'`, `EventStatus` | |
| `revision` | int | NOT NULL, default 1, ≥ 1 | |

Indici: (`match_id`, `pipeline_version`, `type`, `half`) e (`match_id`, `pipeline_version`, `t_video`).

**Fino a M4** c'è un vincolo in più, con un nome, che la migrazione di M4 rimuove: `CONSTRAINT events_pre_m4 CHECK (status = 'confirmed' AND revision = 1)`. Fino ad allora anche il modello Pydantic accetta solo quei due valori.

**Semantica per tipo.** Vale per i detector, per `tools/synth` e per chi scrive il golden set.

| `type` | `team` | `t_video` | `t_end` | `x_pitch`, `y_pitch` |
|---|---|---|---|---|
| `corner` | chi batte | calcio | — | punto di battuta |
| `throw_in` | chi batte | rilascio | — | punto di rimessa |
| `goal_kick` | chi batte | calcio | — | punto di battuta |
| `kickoff` | chi batte | calcio | — | (52.5, 34) |
| `turnover` | **chi recupera** | cambio di possesso | — | punto del recupero |
| `shot` | chi tira | tiro | — | punto del tiro |
| `cross` | chi crossa | cross | — | punto di partenza |
| `pass_final_third` | chi passa | passaggio | — | punto di **ricezione**, nel terzo finale della squadra |
| `counter_attack` | chi attacca | recupero che la innesca | fine della transizione | punto di partenza |
| `press_trigger` | chi pressa | inizio del pressing | fine del pressing, facoltativa | posizione della palla |

«Recuperi per zona» sono eventi `turnover` filtrati per `team` e `Zone`, non una metrica (§8, D7).

**`attrs`.** In v1 non ci sono chiavi di contratto: è un oggetto JSON per diagnostica. Il DSL non filtra su `attrs` e l'assistente non ne cita il contenuto. Quando un tipo avrà campi propri (M2, con il registry), lo schema di quei campi verrà aggiunto qui. È vietato mettere in `attrs` un `track_id` o qualunque cosa che suggerisca l'identità di un giocatore.

### 5.6 `team_metrics`

Aggregati per squadra su finestre di gioco. La `coverage` dice su quanta parte della finestra è calcolato il numero.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `match_id` | text | FK |
| `pipeline_version` | text | NOT NULL |
| `team` | smallint | NOT NULL, `Team` |
| `half` | smallint | NOT NULL |
| `window_start`, `window_end` | real | NOT NULL; **dominio gioco**, `window_end > window_start` |
| `metric` | text | NOT NULL, `MetricName` |
| `value` | real | NULL se e solo se `coverage = 0` |
| `coverage` | real | NOT NULL, [0, 1] |

PK (`match_id`, `pipeline_version`, `team`, `half`, `window_start`, `metric`).

**Finestre:** 300 s di `match_clock` per tempo, allineate a 0: `[0, 300)`, `[300, 600)`, e così via. L'ultima finestra si chiude a fine tempo e può essere più corta.

**`coverage`:** la frazione dei frame campionati nella finestra (tutti, anche quelli non tattici) su cui la metrica era osservabile. «Osservabile» dipende dalla metrica, come da tabella. Chi aggrega più finestre pesa per `coverage`, e sotto 0.5 l'assistente lo dichiara (S1.8).

| `metric` | Unità | Significato | Osservabile quando |
|---|---|---|---|
| `defensive_line_height` | m | distanza della linea difensiva dalla propria porta, nella prospettiva della squadra | ≥ 7 giocatori di movimento visibili |
| `team_width` | m | estensione in y dei giocatori di movimento | ≥ 7 visibili |
| `compactness` | m | distanza media dei giocatori di movimento dal centroide della squadra; più basso vuol dire più compatto | ≥ 7 visibili |
| `possession_share` | frazione, [0, 1] | quota del tempo di possesso della finestra | frame dentro un possesso di qualunque `source` |
| `ppda_proxy` | adimensionale, ≥ 0 | passaggi concessi per azione difensiva, stimati | frame dentro un possesso con `source = 'ball'` |

L'algoritmo esatto di ciascuna stima è in D6/D10 e può cambiare con la versione. Unità e verso («più alto = …») sono di contratto e non cambiano.

### 5.7 `event_embeddings`

Vettori per la ricerca «momenti simili» (M3).

| Colonna | Tipo | Vincoli |
|---|---|---|
| `event_id` | text | PK, `REFERENCES events(id) ON DELETE CASCADE` |
| `pipeline_version` | text | NOT NULL, uguale a quella dell'evento |
| `model` | text | NOT NULL; id del modello di embedding |
| `embedding` | vector(768) | NOT NULL |

Indice HNSW con `vector_cosine_ops`. Si confrontano solo vettori con lo stesso `model`: due partite con versioni diverse possono avere embedding incompatibili. La tabella e l'estensione `vector` nascono con la prima migrazione, anche se la tabella resta vuota fino a M3.

### 5.8 `jobs` — la coda

Postgres usato come coda (ADR-005): chiunque accoda, il worker consuma.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `id` | bigint | PK, `GENERATED ALWAYS AS IDENTITY` |
| `match_id` | text | FK |
| `kind` | text | NOT NULL, `JobKind` |
| `status` | text | NOT NULL, default `'queued'`, `JobStatus` |
| `params` | jsonb | NOT NULL, default `'{}'`; override di config per `reprocess` |
| `attempts` | smallint | NOT NULL, default 0 |
| `created_at` | timestamptz | NOT NULL, default `now()` |
| `locked_at`, `locked_by` | timestamptz, text | NULL finché il job non viene preso; `locked_by` = host del worker |
| `finished_at` | timestamptz | NULL finché non è `done` o `failed` |
| `error` | text | valorizzato se e solo se `status = 'failed'` |

Indici:

- `UNIQUE (match_id) WHERE status IN ('queued', 'running')`: al più un job attivo per partita. È ciò che rende idempotente l'intake (P0.4).
- `(created_at, id) WHERE status = 'queued'`: serve al dequeue.

Dequeue: un'istruzione, una transazione.

```sql
UPDATE jobs
SET status = 'running', locked_at = now(), locked_by = :worker, attempts = attempts + 1
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'queued'
  ORDER BY created_at, id
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

Il worker aggiorna `matches.status` all'inizio e alla fine del job. Se il job va a buon fine, imposta `matches.active_pipeline_version` **nella stessa transazione** in cui scrive l'ultima riga della timeline. Un job `running` con `locked_at` più vecchio di 6 h è considerato orfano: il worker, all'avvio, lo rimette in `queued` se `attempts < 3`, altrimenti lo porta a `failed`.

### 5.9 `pipeline_runs`

L'observability della percezione fino a M2 (ADR-008): una riga per ogni nodo Hamilton eseguito.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `id` | bigint | PK, identity |
| `run_id` | uuid | NOT NULL; una singola esecuzione del driver |
| `job_id` | bigint | NULL, `REFERENCES jobs(id) ON DELETE SET NULL`; NULL per le esecuzioni lanciate a mano |
| `match_id` | text | FK |
| `pipeline_version` | text | NOT NULL |
| `node` | text | NOT NULL; nome della funzione Hamilton |
| `started_at` | timestamptz | NOT NULL |
| `duration_s` | real | NOT NULL, ≥ 0 |
| `ok` | boolean | NOT NULL |
| `rows_out` | bigint | NULL se l'output non è un dataframe |
| `checks` | jsonb | NOT NULL, default `'[]'`; `[{name, passed, message}]` dai `@check_output` |
| `config` | jsonb | NOT NULL; la config Hamilton risolta del run |
| `error` | text | valorizzato se e solo se `ok = false` |

`UNIQUE (run_id, node)`.

### 5.10 `feedback`

Da qui cresce l'eval set: ogni pollice giù è un caso candidato.

| Colonna | Tipo | Vincoli |
|---|---|---|
| `id` | bigint | PK, identity |
| `ts` | timestamptz | NOT NULL, default `now()` |
| `conversation_id` | text | NOT NULL; coincide con `burr_state.app_id` |
| `turn` | int | NOT NULL, ≥ 0 |
| `query_text` | text | NOT NULL |
| `structured_query` | jsonb | NULL se il turno non ha prodotto una `Query` (chitchat, chiarimento) |
| `returned_event_ids` | text[] | NOT NULL, default `'{}'` |
| `rating` | smallint | NOT NULL, `IN (-1, 1)` |
| `note` | text | |

`UNIQUE (conversation_id, turn)`: se l'utente cambia voto, la riga si aggiorna. `returned_event_ids` non ha foreign key, perché gli array non la supportano. Gli id restano comunque risolvibili, perché gli eventi delle versioni vecchie non vengono mai cancellati (§6).

### 5.11 `burr_state`

Lo stato delle conversazioni. **La tabella è del persister PostgreSQL di Burr**, non nostra: la crea `persister.initialize()`, e Alembic la esclude dall'autogenerate (`include_object`). Nessun codice nostro ci scrive SQL. Lo schema, come lo definisce `burr` 0.42:

| Colonna | Tipo | Note |
|---|---|---|
| `partition_key` | text | default `''`; in v1 resta il default |
| `app_id` | text | NOT NULL; **= `conversation_id`** |
| `sequence_id` | integer | NOT NULL |
| `position` | text | NOT NULL; azione corrente |
| `status` | text | NOT NULL |
| `state` | jsonb | NOT NULL |
| `created_at` | timestamp | |

PK (`partition_key`, `app_id`, `sequence_id`, `position`).

Ciò che è di contratto: `app_id = conversation_id`, e le chiavi dentro `state` sono le costanti `S.*` di `packages/assistant`. Rinominarne una rompe il replay delle conversazioni salvate. Se Burr cambia lo schema in un aggiornamento, si aggiorna questa sezione, ma non serve una migrazione nostra.

I persister di Burr 0.42 esistono per psycopg2 e asyncpg, non per psycopg 3. La scelta la fa S1.11.

### 5.12 `eval_cases` e `eval_runs`

Golden set e risultati, per entrambi gli harness. **La fonte di verità dei casi sono i file in `eval/`**, versionati e revisionati in Git. `eval_cases` ne è la materializzazione, caricata con un upsert per `case_id` all'avvio di ogni run, più i candidati che arrivano dal feedback.

`eval_cases`

| Colonna | Tipo | Vincoli |
|---|---|---|
| `case_id` | text | PK |
| `kind` | text | NOT NULL, `EvalKind` |
| `status` | text | NOT NULL, `EvalCaseStatus` |
| `input` | jsonb | NOT NULL |
| `expected` | jsonb | NOT NULL |
| `feedback_id` | bigint | NULL, `REFERENCES feedback(id) ON DELETE SET NULL` |
| `content_hash` | text | NOT NULL; hash di `input` più `expected`, per sapere contro quale versione del caso è stato valutato un run |
| `created_at` | timestamptz | NOT NULL, default `now()` |

`eval_runs`: una riga per (run, caso).

| Colonna | Tipo | Vincoli |
|---|---|---|
| `run_id` | uuid | NOT NULL |
| `case_id` | text | NOT NULL, `REFERENCES eval_cases` |
| `content_hash` | text | NOT NULL; quello del caso al momento del run |
| `git_sha` | text | NOT NULL |
| `pipeline_version` | text | NOT NULL; la versione dei dati valutati (`synth-v1` sul sintetico) |
| `started_at` | timestamptz | NOT NULL |
| `score` | real | NOT NULL |
| `passed` | boolean | NOT NULL |
| `details` | jsonb | NOT NULL, default `'{}'` |

PK (`run_id`, `case_id`).

---

## 6. Versioni: scrittura e lettura

- **Scrittura (D12).** Il worker scrive una versione per partita in una transazione. Se (`match_id`, `pipeline_version`) ha già delle righe, le cancella e le riscrive: rieseguire la stessa versione è idempotente, grazie anche agli id deterministici. Una versione nuova *aggiunge* righe senza toccare quelle vecchie. Alla fine, nella stessa transazione, aggiorna `matches.active_pipeline_version`.
- **Lettura.** Chi legge la timeline (assistente, API, web) filtra **sempre** con `pipeline_version = matches.active_pipeline_version`. Il compilatore del DSL lo fa con un JOIN su `matches`. Le versioni non attive restano per confronto, per l'eval e per risolvere i vecchi `returned_event_ids`.
- **Parquet.** Una versione nuova scrive una partizione nuova. Le partizioni esistenti non si toccano.
- **Pulizia.** Le versioni vecchie si cancellano solo a mano, con una decisione esplicita. Nessun processo automatico lo fa.

---

## 7. Cosa **non** è nel contratto

- Il tracking in Postgres (ADR-005): sta solo in Parquet.
- L'identità dei giocatori, i numeri di maglia, qualunque collegamento tra `track_id` diversi.
- Gli intermedi della percezione (`detections/`, `homography/`) e la cache di Hamilton.
- Le chiavi di `attrs` per tipo di evento, fino a quando non verranno aggiunte in §5.5.
- I tipi di evento senza un produttore: goal, parata, punizione, cartellino, sostituzione (architecture §1). Entrano in `EventType` quando esiste qualcosa che li produce (ADR-013).

---

## 8. Decisioni prese in questa versione

Discrepanze tra le fonti (architecture §3, technical-design §3.3, index.html) e lacune, con la scelta fatta. In review si può contestare ciascuna singolarmente.

| # | Tema | Scelta | Perché |
|---|---|---|---|
| D1 | `events`: `t_start`/`t_end` o `t_video`/`t_end` | **`t_video` + `t_end`** | Il DSL, `ClipRef` e il Parquet usano già `t_video`. È il punto di seek e dichiara il dominio video. `t_start`/`t_end` restano per gli intervalli (`video_segments`, `possessions`) |
| D2 | `view_type`: `unknown` o `graphic` | **tutti e due** | Significano cose diverse: `graphic` è una classe reale (grafica a tutto schermo), `unknown` è il classificatore che non decide. Senza `unknown` un errore del VLM diventerebbe un'etichetta sbagliata |
| D3 | `Team.NA = 255` | **NULL**, niente sentinella | Una sola rappresentazione in Parquet e in Postgres. Polars e SQL gestiscono NULL in modo nativo, mentre 255 si dimentica nei filtri |
| D4 | `matches.pipeline_version` | rinominato **`active_pipeline_version`**, nullable | È un puntatore alla versione da leggere, non provenienza. Una partita appena caricata non ne ha ancora una. La provenienza (`pipeline_version NOT NULL`) sta su ogni riga prodotta |
| D5 | `pitch_length_m`, `pitch_width_m` (architecture §3) | **tolti** | Tutte le coordinate sono nel campo canonico 105×68. Una colonna che nessuno legge è rumore; si aggiunge con una migrazione quando servirà |
| D6 | `possessions`: `start_zone`/`end_zone` | **coordinate** `x/y_start`, `x/y_end` | Le zone si sovrappongono (terzo e fascia), quindi un solo valore è ambiguo. Con le coordinate si usano gli stessi predicati degli eventi |
| D7 | `MetricName.recoveries_by_zone` | **tolto**; i recuperi sono eventi `turnover` | Non è uno scalare: `value real` non può contenere un valore per zona. Architecture §1 elenca già i recuperi per zona tra gli eventi spaziali |
| D8 | «squadra analizzata» non definita | **`matches.team_a_side`** | Senza, A e B non sono collegati a casa e trasferta, e i confronti tra partite non si possono fare |
| D9 | `possessions` assente in technical-design §3.3 | **aggiunta** (§5.4), a partire da index.html e architecture §3 | |
| D10 | `jobs`, `pipeline_runs`, `eval_*` senza DDL | **definiti** (§5.8–5.12) | |
| D11 | Chi crea `burr_state` | **il persister di Burr**, fuori da Alembic | Riprodurre a mano la DDL di una libreria esterna vuol dire divergere al primo aggiornamento |
| D12 | Enum in Postgres | **`text` + `CHECK`** generato dall'enum, non `CREATE TYPE` | Un `CHECK` si modifica in una migrazione normale; `ALTER TYPE … ADD VALUE` ha vincoli transazionali |
| D13 | Normalizzazione del campo | **rotazione di 180°** | Uno specchio invertirebbe le fasce |
| D14 | Dove vive `EventType` | **enum in `core`**; il registry si valida contro l'enum | ADR-013 |

---

## 9. Domande aperte

Non bloccano il congelamento, perché ognuna ha un default sicuro, ma vanno chiuse entro la milestone indicata.

- **O1 (M2)** — Con dati reali, un tipo di evento il cui detector non esiste ancora restituisce zero risultati, e l'assistente potrebbe dire con sicurezza «nessun cross». Serve sapere quali tipi produce una versione: per esempio `event_types` nella config di `pipeline_runs`, letta da `execute_query`. Default fino ad allora: su dati sintetici il problema non si presenta.
- **O2 (M2)** — Le chiavi di `attrs` per tipo, quando arriva il registry (P2.4).
- **O3 (M2)** — Il golden set dell'assistente su dati reali non può legarsi agli `event_id`, perché cambiano con la versione. Deve confrontare per (`type`, `t_video` ± 2 s).

---

## Modifiche

| Versione | Data | Cosa |
|---|---|---|
| 1.0 | 2026-09-25 | Prima stesura (P0.3+S0.2) |
