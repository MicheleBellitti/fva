# fva

Sistema che guarda una partita di calcio (footage broadcast), ne ricava una timeline strutturata, e risponde a domande in italiano portando l'utente al secondo esatto del video.

Due sistemi disaccoppiati, un contratto in mezzo — vedi [`CLAUDE.md`](CLAUDE.md) per il contesto completo e [`docs/`](docs/) per architettura, design tecnico e ADR.

## Quickstart

```bash
uv sync            # installa le dipendenze del workspace
make dev            # postgres, minio, api, burr-ui + migrazioni
make test            # pytest
make check           # lint + types + test — prima di ogni commit
```

## Pre-commit

Il repo usa [pre-commit](https://pre-commit.com/) per far girare in locale, prima di ogni commit, gli stessi controlli della CI: `ruff check` (con `--fix`), `ruff format`, `pyright` in modalità strict e `pytest` (esclusi i marker `gpu` e `llm`).

Setup una tantum dopo aver clonato il repo:

```bash
uv sync
uv run pre-commit install
```

Da quel momento i hook girano automaticamente a ogni `git commit`. Per eseguirli manualmente su tutti i file (utile dopo aver aggiunto o modificato `.pre-commit-config.yaml`):

```bash
uv run pre-commit run --all-files
```

Se un hook fallisce, il commit viene bloccato: correggi (o lascia che `ruff --fix` e `ruff format` correggano da soli) e ricommitta. Per saltare i hook in un caso eccezionale — sconsigliato, e comunque la CI li rifà girare — `git commit --no-verify`.
