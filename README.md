# Picafresa Django

Standalone Django platform for Picafresa. It owns its PostgreSQL schema and does not import,
call, or share write paths with the legacy Go projects.

## Requirements

- Python 3.13, installed automatically by `uv`
- [`uv`](https://docs.astral.sh/uv/)

The development dependency `pgembed` provides a real PostgreSQL 17 server inside the `uv`
environment. It stores local data under `.local/postgres`, starts with the application, and
stops when the application exits. It needs no Docker, system PostgreSQL installation, root
access, password, or remote connection.

## Start locally

```sh
uv sync
uv run python -m tools.devserver
```

The command starts embedded PostgreSQL, applies migrations, and serves the application at
<http://127.0.0.1:8000/>. Pass another address as its sole argument when needed:

```sh
uv run python -m tools.devserver 127.0.0.1:8080
```

Local settings are the default for `manage.py`. To run individual management commands, first
set `PICAFRESA_LOCAL_DATABASE_URL` to another local PostgreSQL instance. Deployed processes
must explicitly select `config.settings.staging` or `config.settings.production` and provide
that environment's database URL and secret settings.

## Quality checks

```sh
uv run pytest
uv run manage.py makemigrations --check
uv run manage.py check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
