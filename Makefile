UV ?= uv
# Prefer the preserved local Python 3.12 environment when it exists.
PYTHON ?= $(if $(wildcard .venv312/bin/python),.venv312/bin/python,.venv/bin/python)

.PHONY: help install api bot worker check test test-web test-e2e release

help:
	@echo "install    Install locked Python and JavaScript dependencies"
	@echo "api        Start development API on http://127.0.0.1:8000"
	@echo "bot        Start Telegram bot (requires .env)"
	@echo "worker     Start background worker (requires .env)"
	@echo "check      Check Python style and formatting"
	@echo "test       Run Python and JavaScript tests"
	@echo "test-e2e   Run browser tests (requires Playwright Chromium)"
	@echo "release    Package sources into dist/slovech.tar.gz"

install:
	$(UV) sync --frozen --python 3.12
	npm ci

api:
	$(PYTHON) -m uvicorn slovech.server:app --reload

bot:
	$(PYTHON) -m slovech.bot

worker:
	$(PYTHON) -m slovech.worker

check:
	$(PYTHON) -m ruff check slovech scripts tests
	$(PYTHON) -m ruff format --check slovech scripts tests

test:
	$(PYTHON) -m pytest -q
	npm test

test-web:
	npm test

test-e2e:
	E2E_PYTHON="$(PYTHON)" npm run test:e2e

release:
	mkdir -p dist
	$(PYTHON) -m scripts.build_release dist/slovech.tar.gz
