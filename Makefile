.PHONY: dev down logs ps migrate revision seed-synth worker smoke-gpu test lint fmt types check

dev:            ## alza i servizi e applica le migrazioni
	docker compose up -d postgres minio minio-init api burr-ui
	@echo "attendo postgres…" && sleep 3
	$(MAKE) migrate
	@echo "API http://localhost:8000  ·  Burr UI http://localhost:7241  ·  MinIO http://localhost:9001"

web:            ## frontend, profilo separato
	docker compose --profile web up -d web

down:           ; docker compose down
clean:          ; docker compose down -v      # cancella anche i dati
logs:           ; docker compose logs -f --tail=100
ps:             ; docker compose ps

migrate:        ; uv run alembic -c packages/core/alembic.ini upgrade head
revision:       ; uv run alembic -c packages/core/alembic.ini revision --autogenerate -m "$(m)"

seed-synth:     ## 3 partite sintetiche con dati sporchi
	uv run python -m tools.synth --matches 3 --dirty

worker:         ## consuma la coda (richiede GPU, gira sull'host)
	uv run python -m worker.main

smoke-gpu:      ## verifica CUDA e YOLO su un frame
	uv run python -m perception.smoke

test:           ; uv run pytest
lint:           ; uv run ruff check .
fmt:            ; uv run ruff format . && uv run ruff check --fix .
types:          ; uv run pyright
check:          lint types test
