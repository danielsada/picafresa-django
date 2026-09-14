UV_RUN := uv run
BASE_BRANCH ?= origin/main

.PHONY: ci sync validate migration-check django-check format-check lint typecheck test coverage changed-coverage

ci: sync validate

sync:
	uv sync --locked

validate: migration-check django-check format-check lint typecheck changed-coverage

migration-check:
	$(UV_RUN) manage.py makemigrations --check --dry-run

django-check:
	$(UV_RUN) manage.py check

format-check:
	$(UV_RUN) ruff format --check .

lint:
	$(UV_RUN) ruff check .

typecheck:
	$(UV_RUN) mypy .

test:
	$(UV_RUN) pytest

coverage:
	$(UV_RUN) pytest --cov=. --cov-report=xml

changed-coverage: coverage
	$(UV_RUN) diff-cover coverage.xml --compare-branch=$(BASE_BRANCH) --fail-under=90
