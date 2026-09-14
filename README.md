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
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

Local settings start embedded PostgreSQL automatically for each command and preserve its data
between commands. Open <http://127.0.0.1:8000/> after starting the server. Set
`PICAFRESA_LOCAL_DATABASE_URL` only when you intentionally want another local PostgreSQL
instance. Deployed processes must explicitly select `config.settings.staging` or
`config.settings.production` and provide that environment's database URL and secret settings.

## Quality checks

```sh
uv run pytest
uv run manage.py makemigrations --check
uv run manage.py check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
