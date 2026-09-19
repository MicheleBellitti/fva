# Football Video Assistant — Architettura e piano di progetto

*Team: 2 sviluppatori. Orchestrazione: Apache Burr (Incubating). Scope: solo feature a fattibilità medio-alta.*

---

## 1. Scope

**Dentro** (fattibilità alta o media, dallo studio precedente):

- Eventi salienti: gol, tiri, parate, corner, punizioni, rimesse, cartellini, sostituzioni
- Eventi spaziali: cross, tiri da fuori area, passaggi nell'ultimo terzo, recuperi per zona, transizioni
- Metriche tattiche **di squadra**: posizioni medie, altezza della linea, ampiezza, compattezza, zone di possesso e recupero, reti di passaggio
- Query in linguaggio naturale → salto al punto del video
- Highlight automatici
- Report di scouting generato su più partite
- Ricerca "momenti simili a questo"

**Fuori, deliberatamente:**

- Metriche individuali precise (l'OCR dei numeri di maglia e gli ID di tracking non reggono)
- Giudizi tattici soggettivi ("era fuori posizione")
- Analisi in tempo reale nelle prime tre fasi

**Assunzione temporale:** ~15h/settimana a testa. Se siete full time, dividete le durate per due e basta.

---

## 2. La decisione architetturale che conta

Il sistema è **due sistemi**, non uno, e vanno tenuti separati perché hanno proprietà opposte:

| | Percezione | Assistente |
|---|---|---|
| Modo | Batch, offline | Interattivo |
| Collo di bottiglia | GPU | Latenza LLM |
| Durata | Decine di minuti | Secondi |
| Fallimento | Riprendi dal checkpoint | Ritenta |
| Stato | Job | Conversazione |

**L'interfaccia tra i due è lo schema della timeline**, ed è l'artefatto più importante del progetto. Va congelato nella Fase 0, prima che qualcuno scriva codice utile.

Questo è anche ciò che rende il progetto parallelizzabile su due persone: Dev B lavora contro timeline sintetiche o annotate a mano fin dal primo giorno, senza aspettare che la CV funzioni.

```
                    ┌──────────────────────────────┐
   video    ────►   │   PERCEPTION (GPU, batch)    │
                    │   detect → track → team      │
                    │   → calibrate → project      │
                    └──────────────┬───────────────┘
                                   │
                          tracks (Parquet)
                                   │
                    ┌──────────────▼───────────────┐
                    │   DERIVATION (CPU, batch)    │
                    │   possessi, eventi, metriche │
                    └──────────────┬───────────────┘
                                   │
                    ═══════ TIMELINE SCHEMA ═══════   ◄── il contratto
                                   │
                    ┌──────────────▼───────────────┐
                    │   ASSISTANT (Burr)           │
                    │   NL → query → tool → answer │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   API (FastAPI) + UI (Next)  │
                    └──────────────────────────────┘
```

---

## 3. Il contratto: schema della timeline

Congelatelo per primo. Ogni modifica successiva costa il doppio.

```sql
-- Postgres: piccolo, interrogabile, transazionale
matches(id, competition, date, home_team, away_team,
        video_uri, duration_s, fps, pitch_length_m, pitch_width_m,
        camera_type,        -- 'broadcast' | 'tactical_fixed'
        status, pipeline_version)

video_segments(match_id, t_start, t_end,
               view_type,   -- 'tactical' | 'replay' | 'closeup' | 'crowd' | 'unknown'
               usable)      -- se l'omografia è affidabile in questo segmento

possessions(id, match_id, t_start, t_end, team,
            start_zone, end_zone, outcome, n_passes)

events(id, match_id, t_start, t_end, type, team,
       x_pitch, y_pitch,
       attrs JSONB,         -- campi specifici per tipo
       confidence REAL,     -- 0-1
       source,              -- 'detector' | 'derived' | 'manual'
       pipeline_version)

event_embeddings(event_id, vector)   -- pgvector, per "momenti simili"

team_metrics(match_id, team, window_start, window_end,
             metric, value, coverage)   -- coverage = frazione di frame osservabili
```

```
-- Parquet su object storage: grande, colonnare, non serve in Postgres
tracks/match_id=<id>/part-*.parquet
  frame, t, track_id, class, team, x_img, y_img, x_pitch, y_pitch, conf, homography_ok
```

**Tre campi non negoziabili, e la ragione:**

- **`confidence` su ogni evento.** L'assistente deve poter dire "probabilmente al 34° minuto" invece di affermare con certezza qualcosa che il detector ha visto al 60%.
- **`coverage` su ogni metrica.** Su footage broadcast vedi un terzo dei giocatori: una metrica calcolata sul 20% dei frame non è confrontabile con una calcolata sull'80%, e senza questo campo lo dimenticherete e produrrete numeri sbagliati che sembrano giusti.
- **`pipeline_version` ovunque.** Quando migliorate il detector, dovete sapere quali risultati sono vecchi. È l'equivalente del pinning della versione del modello.

---

## 4. Stack tecnologico

### 4.1 Percezione — l'ecosistema è maturo, non scrivete da zero

| Componente | Scelta | Note |
|---|---|---|
| Detection | **Ultralytics YOLO** fine-tuned su calcio | Esistono dataset e pesi pubblici già addestrati su giocatori/palla/arbitri |
| Glue e annotazione | **`supervision`** (Roboflow) | Tracking, annotatori, slicing per oggetti piccoli |
| Tracking persone | **BoT-SORT** o ByteTrack | BoT-SORT con ReID è migliore sulle occlusioni, più lento |
| Tracking palla | Inferenza a finestra scorrevole + interpolazione | Il pezzo più fragile. Non aspettatevi miracoli |
| Team clustering | **SigLIP → UMAP → KMeans** sui crop | Robusto ai cambi di luce, molto meglio dell'istogramma dei colori |
| Calibrazione campo | **PnLCalib** o modello keypoint del campo | 32 keypoint → omografia per frame |
| Classificazione inquadratura | Classificatore leggero su feature del frame | Sottovalutato: senza, il 30% del match produce coordinate spazzatura |

**Il riferimento da studiare:** l'ecosistema `roboflow/sports` implementa esattamente questa catena end-to-end fino al radar tattico. Partite da lì, non dal foglio bianco. Esistono anche parecchi fork che aggiungono OCR delle maglie e omografia stabilizzata — leggeteli come reference implementation, non come dipendenza.

**Dataset e benchmark:** SoccerNet è il riferimento del campo. Sei edizioni di challenge, task su action spotting, calibrazione, tracking, ricostruzione dello stato di gioco e VQA sui broadcast, con dataset annotati, protocolli di valutazione e baseline pubbliche. **Usatelo per validare**, anche se il vostro footage sarà altro: è l'unico modo di sapere se i vostri numeri sono decenti o pessimi. Attenzione alla licenza di ricerca.

### 4.2 Assistente

| Componente | Scelta |
|---|---|
| Orchestrazione | **Apache Burr** |
| LLM | Astrazione sul provider, Claude/GPT/Gemini intercambiabili |
| Output strutturato | Pydantic + structured output nativo del provider |
| Query | Text-to-query validato sullo schema, **mai SQL grezzo dal modello** |
| Ricerca semantica | pgvector nello stesso Postgres |
| Osservabilità | Burr UI (integrata) + Langfuse per costi e tracce LLM |

### 4.3 Infrastruttura

| | Scelta | Perché |
|---|---|---|
| Eventi e metadati | Postgres | Uno, non tre. pgvector evita un DB vettoriale separato |
| Tracking | Parquet su MinIO (dev) / S3 (prod) | Colonnare, milioni di righe per partita |
| Video | MinIO / S3, servito in **HLS** | Il salto al timestamp deve essere istantaneo: segmentazione HLS, non download del file intero |
| Coda job | Postgres come coda (`SELECT ... FOR UPDATE SKIP LOCKED`) | Per 2 dev, Redis+Celery è infrastruttura non necessaria. Se cresce, si migra |
| API | FastAPI async + SSE | |
| UI | Next.js + `hls.js` | Il player è il prodotto: deve saltare al secondo esatto |
| Dipendenze | `uv` workspace, monorepo | |

---

## 5. Dove sta Burr, e dove no

Burr è una **macchina a stati per applicazioni che prendono decisioni**: azioni Python decorate che leggono e scrivono uno stato, transizioni tra azioni, persistenza, human-in-the-loop, replay e una UI di debug integrata.

**Usatelo per l'assistente.** È esattamente il suo caso d'uso, e tre delle sue proprietà valgono molto qui:

- **Persistenza dello stato conversazionale** — l'assistente ha memoria della partita in esame, dei filtri attivi, dei risultati precedenti
- **Replay** — puoi rieseguire una conversazione passata contro un prompt nuovo. È la base del vostro eval harness, e Burr ve lo dà gratis
- **UI di tracing integrata** — debuggare una macchina a stati guardando le transizioni invece dei log

**Non usatelo per la pipeline di percezione.** La percezione è un DAG di trasformazioni dati, non un sistema che prende decisioni: non ci sono cicli né scelte a runtime, solo passi in sequenza. Forzarla dentro Burr aggiunge cerimonia senza guadagno. Usate un job runner semplice — o **Hamilton**, che è dei medesimi autori, si integra con Burr ed è progettato esattamente per i DAG di dataflow. La divisione idiomatica è: *Hamilton per "come si calcola", Burr per "cosa faccio adesso"*.

**Zona grigia: l'orchestrazione dell'ingestione.** Un job di ingestione dura decine di minuti, può fallire a metà e deve riprendere. La persistenza di Burr lo copre bene. Se volete usarlo lì, il taglio giusto è: Burr modella gli **stadi** dell'ingestione (validazione → percezione → derivazione → indicizzazione, con retry e ripresa per stadio), Hamilton o codice normale sta **dentro** ogni stadio. Non mettete il loop sui frame in Burr.

### Sketch della macchina a stati dell'assistente

```python
from burr.core import action, State, ApplicationBuilder


@action(reads=["query", "match_context"], writes=["intent", "needs_clarification"])
def classify_intent(state: State, llm) -> State:
    """find_moments | compute_metric | compare_matches | generate_report | chitchat"""
    ...


@action(reads=["query", "schema"], writes=["structured_query", "validation_errors"])
def build_query(state: State, llm) -> State:
    """NL → query Pydantic validata sullo schema. Mai SQL grezzo."""
    ...


@action(reads=["structured_query"], writes=["results", "coverage"])
def execute_query(state: State, repo) -> State:
    """Esecuzione deterministica. Nessun LLM qui."""
    ...


@action(reads=["results"], writes=["answer", "clips", "citations"])
def compose_answer(state: State, llm) -> State:
    """Ogni affermazione cita event_id verificabili."""
    ...


@action(reads=["answer", "citations", "results"], writes=["answer", "grounded"])
def verify_grounding(state: State) -> State:
    """Deterministico: ogni event_id citato era nei risultati?
    Se no, è allucinazione: si scarta o si rigenera."""
    ...


app = (
    ApplicationBuilder()
    .with_actions(
        classify_intent,
        build_query,
        execute_query,
        compose_answer,
        verify_grounding,
        ask_clarification,
    )
    .with_transitions(
        ("classify_intent", "ask_clarification", needs_clarification),
        ("classify_intent", "build_query"),
        ("build_query", "build_query", has_validation_errors),  # retry
        ("build_query", "execute_query"),
        ("execute_query", "compose_answer"),
        ("compose_answer", "verify_grounding"),
        ("verify_grounding", "compose_answer", not_grounded),  # rigenera
    )
    .with_state(messages=[], match_context=None)
    .with_tracker("local")
    .build()
)
```

*(l'API esatta di condizioni e persistenza cambia tra versioni — verificate sui docs, la struttura è quella)*

**Il nodo `verify_grounding` è il pezzo di design migliore del sistema.** Verifica in codice, senza LLM, che ogni evento citato nella risposta fosse effettivamente nei risultati della query. Faithfulness checking deterministico, costo zero. In un assistente che dice "al 34° minuto avete perso palla qui", inventare un minuto è il fallimento più grave possibile, e questo lo rende strutturalmente impossibile.

---

## 6. Struttura del repository

Monorepo, workspace `uv`. La separazione dei package riflette la separazione dei due sistemi, e quindi la divisione del lavoro.

```
football-assistant/
├── pyproject.toml               # uv workspace
├── docker-compose.yml           # postgres, minio, api, ui, burr-ui
├── Makefile                     # make dev / ingest / eval / test
├── AGENTS.md                    # convenzioni per gli agenti di coding
├── docs/
│   ├── adr/                     # decisioni architetturali, numerate
│   ├── schema.md                # IL CONTRATTO
│   └── runbook.md
│
├── packages/
│   ├── core/                    # ← condiviso. Nessuna logica, solo contratti
│   │   ├── models/              # Pydantic: Event, Track, Match, Metric
│   │   ├── schema/              # migrazioni SQL (alembic)
│   │   ├── repo/                # accesso dati, unica porta verso il DB
│   │   └── storage/             # astrazione object storage
│   │
│   ├── perception/              # ← DEV A
│   │   ├── detect/
│   │   ├── track/
│   │   ├── teams/
│   │   ├── calibrate/
│   │   ├── shots/               # classificazione inquadrature
│   │   ├── pipeline.py          # DAG (Hamilton o codice)
│   │   └── models/              # pesi versionati (DVC o hash + object storage)
│   │
│   ├── derivation/              # ← DEV A poi condiviso
│   │   ├── possession.py
│   │   ├── events/              # un detector per tipo di evento
│   │   ├── metrics/             # metriche tattiche di squadra
│   │   └── embeddings.py
│   │
│   ├── assistant/               # ← DEV B
│   │   ├── graph.py             # macchina a stati Burr
│   │   ├── actions/
│   │   ├── query/               # DSL + validazione + compilazione a SQL
│   │   ├── tools/
│   │   ├── prompts/             # versionati, in file, non inline
│   │   └── llm/                 # astrazione provider
│   │
│   ├── api/                     # ← DEV B
│   │   ├── routes/              # /matches /ask /clips /reports
│   │   └── streaming.py         # SSE
│   │
│   └── worker/                  # consumer della coda di ingestione
│
├── apps/
│   └── web/                     # Next.js: player HLS, timeline, chat
│
├── eval/
│   ├── perception/              # ground truth annotato a mano
│   ├── assistant/               # golden set: query NL → event_id attesi
│   └── run.py                   # gira in CI
│
└── tools/
    ├── annotate/                # UI minimale per annotare ground truth
    └── synth/                   # generatore di timeline sintetiche  ← sblocca Dev B
```

Due note sulla struttura. **`core` non contiene logica**: solo modelli, schema e accesso dati. È ciò che impedisce ai due sviluppatori di accoppiarsi. E **`tools/synth` va scritto nella Fase 0**: genera timeline plausibili senza toccare un video, ed è ciò che permette a Dev B di costruire l'intero assistente mentre Dev A è ancora a litigare con l'omografia.

---

## 7. Fasi e divisione del lavoro

### Fase 0 — Il contratto (2 settimane, insieme)

Entrambi sullo stesso lavoro, perché sbagliare qui costa dopo.

- Schema della timeline scritto, discusso, congelato in `docs/schema.md`
- Modelli Pydantic e migrazioni in `core`
- `docker-compose` che gira: Postgres, MinIO, API vuota, UI vuota
- **Generatore di timeline sintetiche** funzionante
- Un video reale caricato, segmentato in HLS, riproducibile nella UI con salto al secondo
- 3-4 ADR iniziali

**Fatto quando:** `make dev` alza tutto, e nella UI si apre un video e si salta a un timestamp arbitrario.

### Fase 1 — I due binari (4 settimane, in parallelo)

**Dev A — percezione:**
detection su frame campionati; tracking con ID stabili; clustering squadre; classificatore di inquadratura; omografia con gate di stabilità; proiezione su coordinate campo; output in Parquet. Un'unica partita, fatta bene.

*Fatto quando:* per una partita esiste il Parquet con coordinate campo, e il radar 2D sovrapposto è visivamente corretto per almeno l'80% dei segmenti tattici.

**Dev B — assistente:**
macchina a stati Burr completa sui dati sintetici; DSL di query con validazione Pydantic; text-to-query; `verify_grounding`; endpoint `/ask` in streaming; UI con chat e salto ai risultati.

*Fatto quando:* su timeline sintetica, "mostrami tutti i corner del secondo tempo" restituisce i momenti giusti e il player ci salta.

**Sincronizzazione:** stand-up scritto due volte a settimana, e **ogni modifica allo schema è una PR con entrambi come reviewer.** È l'unica regola di processo che serve davvero.

### Fase 2 — Convergenza (4 settimane)

**Dev A:** derivazione degli eventi. Possessi, poi i detector per tipo. Ordine consigliato: prima quelli geometrici e deterministici (corner, rimessa, fuori campo, cambio di possesso), poi quelli statistici (tiro, cross, passaggio nell'ultimo terzo). Ogni detector produce `confidence`.

**Dev B:** eval harness per l'assistente (golden set di 40-50 query con event_id attesi, in CI); highlight automatici; report di scouting su singola partita; Langfuse.

**Insieme:** collegate i due binari. Il primo passaggio da sintetico a reale rompe cose — mettete in conto una settimana di assestamento e non spaventatevi.

*Fatto quando:* una domanda in italiano su una partita vera restituisce i momenti giusti, e l'eval gira in CI.

### Fase 3 — Multi-partita (4 settimane)

**Dev A:** metriche tattiche di squadra con `coverage`; aggregazione su più partite; embedding degli eventi per la ricerca di similarità.

**Dev B:** query comparative tra partite; report di scouting su N partite; ricerca "momenti simili"; UI di confronto.

*Fatto quando:* "come si comporta questa squadra in uscita dal pressing nelle ultime 5 partite" produce un report con clip a supporto e numeri con copertura dichiarata.

### Fase 4 — Live (aperta)

**Da affrontare solo dopo la Fase 3, e sapendo che è un progetto a sé.** Cosa cambia davvero:

- Buffer scorrevole invece del file completo
- **Nessun lookahead**: niente smoothing all'indietro dell'omografia, niente interpolazione della traiettoria della palla usando il futuro. L'accuratezza scende, non di poco
- Budget di latenza esplicito (5-30 s è realistico; sotto è un altro progetto)
- Eventi rivedibili: un evento emesso con bassa confidenza può essere corretto 10 secondi dopo, e la UI deve saperlo gestire
- La GPU deve reggere il tempo reale, il che significa modelli più piccoli e frame rate più basso

**La via di mezzo che vi consiglio di considerare seriamente:** nel dilettantismo e nel semi-pro, "durante la partita" nella pratica significa **all'intervallo**. Processare il primo tempo mentre si gioca e avere l'assistente pronto al 46° è enormemente più facile del vero streaming, e per un allenatore è quasi altrettanto utile. Se il prodotto punta lì, la Fase 4 diventa un problema di scheduling invece che di latenza.

---

## 8. Valutazione

Due harness separati, come sono separati i due sistemi. Entrambi in CI.

**Percezione** (ground truth annotato a mano, 10-15 min di video bastano per iniziare):
- Detection: mAP su giocatori e palla, separatamente — la palla sarà molto peggio, è normale
- Tracking: HOTA o MOTA, e conteggio degli scambi di ID
- Omografia: errore di riproiezione in metri sui keypoint, e **frazione di frame con omografia accettata**
- Eventi: precision e recall per tipo, con tolleranza temporale (±2 s)

**Assistente** (golden set di 40-50 query in italiano):
- La query strutturata generata è valida ed eseguibile? (deterministico)
- Gli event_id restituiti corrispondono a quelli attesi? Precision e recall
- La risposta è grounded? (deterministico, via `verify_grounding`)
- La risposta è utile? (LLM-as-judge, campione, judge di famiglia diversa)

**La proprietà che rende tutto questo praticabile:** il replay di Burr vi permette di rieseguire conversazioni reali contro prompt o modelli nuovi. Il vostro eval set cresce dai fallimenti veri invece che dall'immaginazione.

---

## 9. Deployment

**Dev:** `docker compose` — Postgres+pgvector, MinIO, API, worker, Next, Burr UI. Tutto in locale sulla 4070.

**Produzione, due deployable con profili opposti:**

| | `ingest-worker` | `api` |
|---|---|---|
| Risorse | GPU | CPU |
| Modo | Batch, coda | Richiesta/risposta |
| Scala | 1-N, on demand | Serverless, scala a zero |
| Dove | GPU on-prem o noleggio orario | Cloud Run / Container Apps |

Il worker GPU è la voce di costo. Per iniziare, la 4070 di casa che consuma la coda è perfettamente adeguata: l'ingestione è asincrona, nessuno aspetta. Il noleggio orario di GPU cloud ha senso solo quando dovete processare dieci partite in una notte.

**Il resto:** Postgres gestito, object storage, CDN davanti all'HLS (i segmenti video sono la banda), secret manager, CI che gira test **ed eval** e blocca il merge sotto soglia.

**Versionamento dei modelli:** i pesi non stanno in Git. Object storage con hash, riferimento in config, `pipeline_version` scritto su ogni riga prodotta. Quando cambiate detector, sapete cosa va rigenerato — e questa è la ragione per cui quel campo era non negoziabile.

---

## 10. I rischi, in ordine di probabilità

1. **Lo schema cambia in Fase 2.** Quasi certo. Mitigazione: migrazioni fin dal giorno uno, e accettate che una migrazione dolorosa sia il prezzo, non un fallimento.
2. **Il tracking della palla non funziona bene.** Molto probabile. Mitigazione: progettate i detector di eventi per degradare con grazia quando la palla manca, e dichiarate confidenza bassa invece di tacere.
3. **I due binari non si incastrano.** Mitigazione: il generatore sintetico deve produrre dati *realisticamente sporchi* — buchi, confidenze basse, coverage parziale — non dati perfetti. Se Dev B sviluppa su dati puliti, la convergenza sarà brutale.
4. **Scope creep sulle feature tattiche.** La tentazione di aggiungere "solo un'altra metrica" è costante. Mitigazione: la lista della sezione 1 è chiusa fino alla Fase 3.
5. **Diritti sul footage.** Se il progetto deve uscire dalle vostre macchine, serve footage vostro o di un club. Decidetelo in Fase 0, perché determina se ottimizzate per broadcast o per grandangolare fisso — e sono due pipeline diverse.

---

## 11. Le tre cose da non sbagliare

1. **Congelate lo schema prima di scrivere codice.** È l'unica decisione che, se sbagliata, costa settimane.
2. **`confidence` e `coverage` su ogni numero.** Un assistente che afferma con sicurezza cose stimate al 40% è peggio di uno che non risponde.
3. **`verify_grounding` deterministico.** In un sistema che dice "al minuto X è successo Y", l'evento inventato è il fallimento che distrugge la fiducia. Rendetelo strutturalmente impossibile, non improbabile.
