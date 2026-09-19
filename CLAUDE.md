# CLAUDE.md

Contesto per agenti di coding su questo repository. Tienilo corto: viene caricato a ogni sessione. I dettagli stanno nei documenti linkati, non qui.

## Cos'è

Sistema che guarda una partita di calcio (footage broadcast), ne ricava una **timeline strutturata**, e risponde a domande in italiano portando l'utente al secondo esatto del video.

Due sistemi disaccoppiati, un contratto in mezzo:

```
video → PERCEZIONE (batch, GPU, Hamilton) → [ timeline ] → ASSISTENTE (interattivo, LLM, Burr) → UI
```

**Non si chiamano mai direttamente.** Comunicano solo attraverso Postgres e il bucket S3.

## La regola che conta più di tutte

`packages/core/` e `docs/schema.md` sono **il contratto**. Ogni modifica lì:

1. richiede una PR con **due reviewer**
2. richiede una migrazione Alembic
3. richiede l'aggiornamento di `docs/schema.md` nello stesso commit

Se stai per cambiare uno schema, un enum o la firma di un nodo del DAG, **fermati e chiedi**. Non è una modifica locale.

## Comandi

```bash
make dev          # postgres, minio, api, burr-ui + migrazioni
make test         # pytest
make check        # lint + types + test — esegui questo prima di ogni commit
make seed-synth   # 3 partite sintetiche (dati sporchi, deliberatamente)
make worker       # consuma la coda; richiede GPU, gira sull'host
make migrate      # applica le migrazioni
make revision m="descrizione"
```

## Mappa

| Percorso | Cosa | Leggi prima |
|---|---|---|
| `packages/core/` | enum, modelli, repo, migrazioni — **il contratto** | `docs/schema.md` |
| `packages/perception/` | DAG Hamilton: video → tracking in coordinate campo | `docs/technical-design.md` §4 |
| `packages/derivation/` | DAG Hamilton: tracking → possessi, eventi, metriche | `docs/technical-design.md` §4 |
| `packages/assistant/` | macchina a stati Burr, DSL, compilatore SQL | `docs/technical-design.md` §5 |
| `packages/api/` | FastAPI, streaming SSE | |
| `packages/worker/` | consumer della coda | |
| `apps/web/` | Next.js, player HLS con seek | |
| `tools/synth/` | generatore di timeline sintetiche | |
| `docs/index.html` | sito del progetto (task, milestone, architettura) | |

## Prima di lavorare su…

- **qualunque cosa tocchi i dati** → `docs/schema.md`
- **architettura, chi scrive cosa** → `docs/architecture.md`
- **dettagli di un nodo o di un'azione** → `docs/technical-design.md`
- **perché una scelta è quella** → `docs/adr/`
- **cosa fare adesso** → `docs/index.html`, pagina Lavoro

## Convenzioni

**Codice**

- Python 3.12, type hints ovunque, `pyright` in modalità strict
- **Polars**, non pandas. Pandas solo dove una libreria lo impone, convertendo al bordo
- Pydantic v2 con `model_config = {"extra": "forbid"}` su ogni modello
- Niente chiavi stringa sparse: costanti (`S.RESULTS`, `Cls.BALL`, `ViewType.TACTICAL`)
- I prompt stanno in file sotto `prompts/`, versionati. Mai inline nel codice

**Il DAG**

- Un nodo è **uno stadio su una partita o un blocco di minuti**, mai su un frame. Il loop sui frame vive *dentro* il nodo
- I nomi delle funzioni sono API pubblica: rinominarli rompe tutto a valle
- Le varianti si fanno con `@config.when`, non con `if` dentro il nodo
- I controlli di sanità sono `@check_output` sul nodo, non script separati

**L'assistente**

- **L'LLM non scrive mai SQL.** Produce un oggetto Pydantic dal DSL; il compilatore genera SQL con parametri bindati
- `execute_query` e `verify_grounding` sono deterministici: nessuna chiamata LLM lì dentro
- Ogni affermazione nella risposta cita `event_id` verificabili

**Dati**

- `confidence`, `coverage`, `pipeline_version`: obbligatori, mai null
- Nuova `pipeline_version` = nuova partizione Parquet. Mai sovrascrivere
- I pesi dei modelli non stanno in Git: object storage, nome = sha
- **`track_id` non è un giocatore.** Cambia quando il giocatore esce dall'inquadratura. Nessuna logica a valle può dipendere dall'identità a lungo termine

**Git**

- Branch: `perc/<topic>`, `asst/<topic>`, `core/<topic>`
- Conventional commits: `feat(perception): …`
- PR sotto le 400 righe. Squash merge. `main` sempre verde
- Aggiorna `STATUS.md` quando chiudi un task

## Test

- `tests/test_graphs.py` costruisce il DAG su **ogni combinazione di config** e il grafo Burr. È il guardiano contro gli errori di nome: se lo rompi, fermati
- Ogni file di `config/` è validato contro il suo schema Pydantic in un test parametrizzato
- Marker `gpu` e `llm` per i test che richiedono hardware o costano: esclusi dalla CI
- I detector di eventi si testano su dataframe Polars costruiti a mano, senza video

## Cose da non fare

- Non aggiungere un database. Postgres fa eventi, vettori, coda, stato Burr e feedback
- Non mettere il tracking in Postgres: è Parquet
- Non introdurre pandas, Redis, Celery o un vector DB dedicato senza un ADR
- Non mettere un `if camera == …` dentro un nodo: usa `@config.when`
- Non chiamare l'API dal worker o viceversa: passano dal database
- Non toccare `status` e `revision` sugli eventi prima di M4: restano `confirmed` e `1`
- Non committare `.env`, pesi, video o Parquet

## Stato

Fase corrente e task aperti: `STATUS.md` e la pagina Lavoro di `docs/index.html`.

Molti nodi sono **stub che sollevano `NotImplementedError` con l'id del task** (`P1.7`, `S1.3`). È deliberato: le firme sono il contratto, le implementazioni arrivano nell'ordine del piano. Se ne incontri uno, controlla se il task è assegnato prima di riempirlo.
