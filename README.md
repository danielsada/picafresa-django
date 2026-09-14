# Picafresa Django

Standalone Django platform for Picafresa. It owns its PostgreSQL schema and does not import,
call, or share write paths with the legacy Go projects.

## Requirements

- Python 3.13, installed automatically by `uv`
- [`uv`](https://docs.astral.sh/uv/)

The development dependency `pgembed` provides a real PostgreSQL 17 server inside the `uv`
environment. It stores local data under `.local/postgres`, starts with the application, and
stops when the application exits. It needs no Docker, system PostgreSQL installation, root
access, password, or remote connection. Provisioning creates the `picafresa_local` database
and a `picafresa_local_app` login that cannot create roles or databases, does not own the
database, and cannot connect to other databases.

## Start locally

```sh
uv sync
uv run tools/provision_postgres.py provision-local
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

Local settings also provision embedded PostgreSQL automatically for each command and preserve
its data between commands. Open <http://127.0.0.1:8000/> after starting the server. Set
`PICAFRESA_LOCAL_DATABASE_URL` only when you intentionally want another local PostgreSQL
instance; the guard accepts only local hosts or Unix sockets and requires the expected local
database and role names.

## Provision staging PostgreSQL

Staging must use a dedicated PostgreSQL 17 server or partition separate from production. The
provisioner creates a `picafresa_staging` database and a `picafresa_staging_app` login
restricted to that database. Django migrations create the application tables inside it; do not
create a parallel staging table inside production.

Load these values from your deployment secret environment:

```sh
export PICAFRESA_STAGING_DATABASE_HOST=staging-postgres.example.com
export PICAFRESA_STAGING_DATABASE_URL='postgresql://picafresa_staging_app:<password>@staging-postgres.example.com/picafresa_staging?sslmode=require'
export PICAFRESA_STAGING_DATABASE_ADMIN_URL='postgresql://<provisioner>:<password>@staging-postgres.example.com/postgres?sslmode=require'
export PICAFRESA_PRODUCTION_DATABASE_HOST=production-postgres.example.com
export PICAFRESA_PRODUCTION_DATABASE_URL='postgresql://picafresa_production_app:<password>@production-postgres.example.com/picafresa_production?sslmode=require'
```

Run provisioning once with the staging provisioning role, then remove its URL from the
application runtime environment:

```sh
uv run tools/provision_postgres.py provision-staging
uv run tools/provision_postgres.py verify-staging
DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py check --deploy
```

Commands fail before connecting when required configuration is absent, when the effective
staging names or host do not match the allowlisted values, or when staging resolves to the
configured production server. Provisioning also refuses a server containing another
application database. The provisioning role is separate from the application role and must
never be committed to a file.

## Quality checks

```sh
uv run pytest
uv run manage.py makemigrations --check
uv run manage.py check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
