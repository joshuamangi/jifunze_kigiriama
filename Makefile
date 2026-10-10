PYTHON ?= /opt/homebrew/bin/python3.11
VENV := .venv
BIN := $(VENV)/bin
ENV_FILE ?= .env
ENV_PATH := $(abspath $(ENV_FILE))

.PHONY: install run test lint audit-secrets migrate seed create-user bench-argon2 download-model bench-embed reindex

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install

run:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; \
	$(BIN)/python -c "from app.config import Settings; Settings.from_env()" && \
	exec $(BIN)/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

audit-secrets:
	$(BIN)/pre-commit run gitleaks --all-files

# Targets named by docs/IMPLEMENTATION.md; implemented in later stages.
migrate:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python -m app.migrate

seed:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python -m app.seed

create-user:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; \
	$(BIN)/python scripts/create_user.py --username "$(NAME)" --role "$(or $(ROLE),member)"

bench-argon2:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python scripts/bench_argon2.py

download-model:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python scripts/download_model.py

bench-embed:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python scripts/bench_embed.py $(ARGS)

reindex:
	set -a; [ ! -f $(ENV_PATH) ] || . $(ENV_PATH); set +a; $(BIN)/python scripts/reindex.py
