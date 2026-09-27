# STATUS

## Fase corrente

**M0 — Il contratto** · Sprint 1: 28/09 → 11/10/2026 · 2 dev, assegnazione libera · capacità 40 h

**Goal dello sprint:** contratto congelato, scheletri costruibili, primo video con seek.

**Prerequisito (entro il 27/09):** merge di `infra/docker-setup` e `infra/precommit-hooks` — chiude lo scaffolding (P0.1, P0.2, S0.1, S0.6).

I ticket vivono su Cadence; il file di import è `docs/sprints/football-video-assistant-sprint-01.json`.

## Sprint 1

| Board | Ticket | h | Stato |
|---|---|---|---|
| P0.3+S0.2 | Scrivere e congelare `docs/schema.md` (in coppia) | 6 | in review — bozza v1.0 + ADR-013 |
| S0.3 | `core/models` + enum + Alembic e prima migrazione | 5 | todo |
| S0.5 | DSL di query | 4 | todo |
| P0.10+S0.9 | Chiudere ADR-006, ratificare gli ADR, CODEOWNERS | 2 | todo |
| S0.4 | `tools/synth`: timeline sintetiche sporche | 6 | todo |
| P0.6 | Scheletro Hamilton + `test_graphs` | 4 | todo |
| S0.8 | Scheletro Burr + `test_graphs` | 3 | todo |
| P0.4 | Intake: transcodifica, HLS, upload, `matches`/`jobs` | 4 | todo |
| S0.7 | Next.js + player hls.js con seek | 4 | todo |
| P0.5 | *(stretch)* CLI allineamento e orientamento | 2 | todo |
| P0.9 | *(stretch)* Adapter `pipeline_runs` | 2 | todo |

**Rimandati allo sprint 2:** P0.7 notebook Kaggle, P0.8 frame per annotazione.
