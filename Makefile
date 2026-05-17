# =============================================================================
# Simandou Screening — Makefile
#
# Usage rapide :
#   make help          # liste les cibles
#   make install       # installe deps prod + dev
#   make run           # lance l'API en dev (uvicorn reload)
#   make worker        # lance un worker Celery local
#   make test          # tous les tests (unit + integration)
#   make test-unit     # tests unitaires seulement (rapides, no Docker)
#   make test-int      # tests d'intégration (testcontainers)
#   make lint          # ruff check
#   make format        # ruff format
#   make migrate       # alembic upgrade head
#   make migration MSG="add foo"   # nouvelle migration auto
# =============================================================================

PYTHON ?= .venv/bin/python
PIP    := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
RUFF   := $(PYTHON) -m ruff
ALEMBIC := $(PYTHON) -m alembic

.PHONY: help install run worker test test-unit test-int lint format \
        migrate migration clean-pyc coverage

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

run: ## Start API in dev mode (uvicorn, autoreload)
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Start a Celery worker (needs REDIS_URL set)
	$(PYTHON) -m celery -A app.core.celery_app:celery_app worker --loglevel=info -c 4

test: ## Run all tests
	$(PYTEST) -v

test-unit: ## Unit tests only (fast, no Docker)
	$(PYTEST) -v -m unit

test-int: ## Integration tests only (requires Docker)
	$(PYTEST) -v -m integration

coverage: ## Run tests with coverage report
	$(PYTEST) --cov=app --cov-report=term-missing --cov-report=html
	@echo "HTML coverage in htmlcov/index.html"

lint: ## Lint the codebase with ruff
	$(RUFF) check app/ tests/

format: ## Format the codebase with ruff
	$(RUFF) format app/ tests/
	$(RUFF) check --fix app/ tests/

migrate: ## Apply pending Alembic migrations
	$(ALEMBIC) upgrade head

migration: ## Create a new auto-generated migration (use: make migration MSG="add foo")
	@[ -n "$(MSG)" ] || (echo "Usage: make migration MSG=\"your message\""; exit 1)
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

clean-pyc: ## Remove Python bytecode
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
