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

## Platform operations

Django Admin is reserved for active superusers acting as platform operators. It supports
reseller portfolios, business tenants, independent assistance providers, tenant-specific
provider contact overrides, and composable reseller, provider-tenant, and modeled tenant
assignments. Organization deletion is soft, scope deletion revokes the assignment, and these
privileged changes are recorded in the read-only audit event administration.

## Reseller back office

An active user with a non-revoked reseller-administrator assignment signs in at `/` and
lands at `/cartera/` (also linked from **Mi cuenta**). Each list contains at most 20 records
per page, limited to active, non-deleted businesses in the user's active reseller portfolios.
Provider-employee and tenant-administrator assignments never expand this administrative scope;
the staff flag alone does not grant Django Admin access.

Reseller administrators can edit a business's name and IANA timezone and the contact overrides
of its existing, non-deleted provider relationships. Clearing an override restores the canonical
provider contact for that field. Inactive relationships remain inspectable, but inactive or
deleted providers are unavailable. The server fixes business/reseller/provider references from
the authorized URL rather than accepting them from forms. Every actual change is audited with
the actor, reseller scope, correlation ID, and changed field names, not contact values.

Business creation, portfolio reassignment, lifecycle controls, global provider contact changes,
and role grants remain platform-only here. Contract creation and lifecycle workflows belong to
ticket 09. Pricing, government identifiers, and raw audit data are not exposed in this back office.
Pages use labeled server-rendered forms, keyboard navigation, and a responsive layout without
requiring JavaScript.

## Draft and publish Plans

`/planes/` is available from the reseller portfolio, **Mi cuenta**, and the read-only catalog
in platform Django Admin. Reseller administrators see only Plans owned by their active reseller
portfolios; platform operators can inspect all historical Plans. Plan and version lists use
20-record pages. Tenant and provider roles do not grant catalog administration.

A Plan has one permanent reseller and assistance provider. Replacing its provider requires a
new Plan identity, as explained in the Spanish forms. An optional internal amount and explicit
currency (MXN by default) are editable and visible only to platform operators. Reseller edits
preserve existing internal pricing.

Each numbered draft contains an effective start and exclusive end date, a positive duration in
calendar months, descriptive coverage terms, and member-facing services. The author can edit
the draft and add or remove services without JavaScript (up to 100 services in the form).
Only a different authorized reseller administrator or platform operator can publish it,
including when the author is a platform operator. Reviewers cannot edit another author's draft
and then approve their own changes. Inactive resellers or inactive/deleted providers block
mutations without removing operator access to historical terms.

Publication freezes the complete version and its services. Later terms use a new numbered
draft; earlier terms are never overwritten. PostgreSQL constraints and triggers protect the
permanent identity, author, two-person publication, and published terms, including against ORM
bulk changes or service reparenting. Service operations serialize draft numbering, editing,
and publication. Django Admin provides inspection and links to these guarded workflows rather
than a second mutation path.

Plan creation, edits, drafts, publication, and rejected privileged requests produce append-only
audit evidence with actor, object references, correlation ID, and operation/status metadata, not
pricing, submitted terms, or contact values. Failed service mutations roll back before recording
their rejection; callers must not wrap these entrypoints in a transaction that subsequently
rolls back the audit event.

## Live-testing demo

From this project directory, start a local-only demo with:

```sh
bash tools/run_local_demo.sh
```

The script applies local migrations, seeds the example portfolios, then serves
<http://127.0.0.1:8000/>. Stop it with Ctrl+C. It explicitly uses `config.settings.local`;
the seed command refuses staging, production, and other settings modules.

| Portfolio | Example businesses | Login |
| --- | --- | --- |
| Platform operator | All portfolios through Django Admin | `demo.operador@example.test` |
| Archers | M21, HUC | `demo.archers@example.test` |
| Carlos Asistencias | Asistencias Centro, Asistencias Norte | `demo.carlos@example.test` |
| Salubritas SA de CV | Clínica Centro Demo, Clínica Sur Demo | `demo.salubritas@example.test` |
| Pedro Beneficios | Beneficios Centro, Beneficios Norte | `demo.pedro@example.test` |

Each reseller starts with 23 businesses, including synthetic numbered branches to exercise
pagination, and relationships with **Asistencias Cuatro** and **Asistencias MENOS**. Each reseller login
is verified and scoped only to its own portfolio. All contacts are fictitious; the named
portfolios and businesses are examples, not imported customer data.

Every run assigns fresh random passwords to all demo accounts and prints them to the terminal
as JSON. Save the current output locally for testing; never commit it. After the first successful
seed, an immutable audit marker identifies the existing portfolios by ID: reruns rotate only the
demo passwords and do not recreate renamed organizations or restore revoked permissions. Existing
organization/contact edits are preserved, and conflicting account state or cross-portfolio
permissions abort the seed without partial changes.

To seed without starting the server:

```sh
DJANGO_SETTINGS_MODULE=config.settings.local uv run manage.py seed_local_demo
```

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
