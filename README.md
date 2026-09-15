# Picafresa Django

Standalone Django platform for Picafresa. It owns its PostgreSQL schema and does not import,
call, or share write paths with the legacy Go projects.

## Requirements

- Python 3.13, installed automatically by `uv`
- [`uv`](https://docs.astral.sh/uv/)
- GNU Make

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

Staging uses a PostgreSQL 18 database separate from production. A dedicated server remains the
default, but an existing shared Azure PostgreSQL server can be used through an explicit opt-in.
The provisioner creates a `picafresa_staging` database and a `picafresa_staging_app` login
without administrative or cross-database object privileges. Django migrations create the
application tables inside it.

Load these values from your deployment secret environment:

```sh
export PICAFRESA_STAGING_DATABASE_HOST=staging-postgres.example.com
export PICAFRESA_STAGING_DATABASE_URL='postgresql://picafresa_staging_app:<password>@staging-postgres.example.com/picafresa_staging?sslmode=require'
export PICAFRESA_STAGING_DATABASE_ADMIN_URL='postgresql://<provisioner>:<password>@staging-postgres.example.com/postgres?sslmode=require'
export PICAFRESA_ALLOW_SHARED_STAGING_SERVER=true
export PICAFRESA_PRODUCTION_DATABASE_HOST=production-postgres.example.com
export PICAFRESA_PRODUCTION_DATABASE_URL='postgresql://picafresa_production_app:<password>@production-postgres.example.com/picafresa_production?sslmode=require'
export GOVERNMENT_IDENTIFIER_LOOKUP_KEY='<independent-random-secret>'
```

Run provisioning once with the staging provisioning role, then remove its URL from the
application runtime environment:

```sh
uv run tools/provision_postgres.py provision-staging
uv run tools/provision_postgres.py verify-staging
DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py migrate
DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py check --deploy
```

For manual provisioning through DBeaver, follow the two execution stages in
[`tools/provision_staging_dbeaver.sql`](tools/provision_staging_dbeaver.sql). The script
generates the application password; copy it from DBeaver's output directly into the staging
secret store and clear the output afterward.

Commands fail before connecting when required configuration is absent or when the effective
staging names or host do not match the allowlisted values. A staging target on the production
server is rejected unless `PICAFRESA_ALLOW_SHARED_STAGING_SERVER=true` is explicitly set.
Shared-server mode never changes `PUBLIC` connection privileges on existing databases. The
provisioning role is separate from the application role and must never be committed to a file.

## Quality checks

Install the locked development environment and run the complete local validation workflow:

```sh
make ci
```

`make ci` installs the exact `uv.lock` environment and runs the same validation entrypoint used
by GitHub Actions. `make validate` checks migration consistency and Django configuration,
verifies Ruff formatting and linting, runs strict mypy, executes the complete test suite against
embedded PostgreSQL, and rejects changed Python code below 90% coverage. The test suite includes
unit and PostgreSQL integration tests plus marked role-facing journeys without production
services or credentials. Changed-code coverage compares with `origin/main` by default; use
another merge base when needed:

```sh
make changed-coverage BASE_BRANCH=origin/your-base-branch
```

Individual gates are available as `make migration-check`, `make django-check`,
`make format-check`, `make lint`, `make typecheck`, `make test`, and `make coverage`.
Use `make sync` to install only the locked environment.

Generated Django migrations are excluded from Ruff and strict annotation checks. Coverage also
excludes generated migrations, Django's ASGI/WSGI launchers, the management launcher, and the
embedded PostgreSQL settings adapter because those are generated or process-bound integration
surfaces rather than application logic.
