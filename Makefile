UV := $(shell for p in /usr/local/adyen/bin/uv $$HOME/.local/bin/uv; do [ -x $$p ] && echo $$p && exit; done; command -v uv)

.PHONY: install browsers run format lint typecheck test check seed

install:
	$(UV) sync

browsers:
	$(UV) run playwright install chromium

run:
	$(UV) run python -m f2f

format:
	$(UV) run ruff format src tests scripts
	$(UV) run ruff check --fix src tests scripts

lint:
	$(UV) run ruff format --check src tests scripts
	$(UV) run ruff check src tests scripts

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

check: format lint typecheck test

seed:
	$(UV) run python scripts/seed_templates.py "$(XLSX)"
