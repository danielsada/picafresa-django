import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from django.core.exceptions import ImproperlyConfigured
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

POSTGRES_MAJOR_VERSION = 17
LOCAL_DATABASE_NAME = "picafresa_local"
LOCAL_DATABASE_ROLE = "picafresa_local_app"
STAGING_DATABASE_NAME = "picafresa_staging"
STAGING_DATABASE_ROLE = "picafresa_staging_app"


@dataclass(frozen=True)
class DatabaseTarget:
    url: str
    role: str
    password: str | None
    host: str | None
    port: int | None
    database: str


@dataclass(frozen=True)
class DatabaseReport:
    database: str
    role: str
    postgres_major_version: int
    is_superuser: bool
    can_create_database: bool
    can_create_role: bool
    owns_database: bool
    can_create_in_public_schema: bool
    can_connect_other_databases: bool


def required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not value:
        raise ImproperlyConfigured(f"Set the {name} environment variable.")
    return value


def parse_database_url(url: str, *, variable_name: str) -> DatabaseTarget:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured(f"{variable_name} must be a PostgreSQL URL.")

    try:
        parameters = conninfo_to_dict(url)
    except psycopg.ProgrammingError as error:
        raise ImproperlyConfigured(f"{variable_name} is not a valid PostgreSQL URL.") from error

    role = cast(str, parameters.get("user", ""))
    database = cast(str, parameters.get("dbname", ""))
    if not role or not database:
        raise ImproperlyConfigured(f"{variable_name} must include both a role and database name.")

    host = cast(str | None, parameters.get("host"))
    port_value = cast(str | None, parameters.get("port"))
    if (host and "," in host) or (port_value and "," in port_value):
        raise ImproperlyConfigured(f"{variable_name} must target exactly one PostgreSQL server.")

    return DatabaseTarget(
        url=url,
        role=role,
        password=cast(str | None, parameters.get("password")),
        host=host,
        port=int(port_value) if port_value else None,
        database=database,
    )


def validate_local_database_url(url: str) -> DatabaseTarget:
    target = parse_database_url(url, variable_name="PICAFRESA_LOCAL_DATABASE_URL")
    local_hosts = {None, "", "localhost", "127.0.0.1", "::1"}
    is_local_socket = target.host is not None and Path(target.host).is_absolute()
    if target.host not in local_hosts and not is_local_socket:
        raise ImproperlyConfigured(
            "PICAFRESA_LOCAL_DATABASE_URL must use a local PostgreSQL host or Unix socket."
        )
    if target.database != LOCAL_DATABASE_NAME or target.role != LOCAL_DATABASE_ROLE:
        raise ImproperlyConfigured(
            "PICAFRESA_LOCAL_DATABASE_URL must use database "
            f"{LOCAL_DATABASE_NAME} and role {LOCAL_DATABASE_ROLE}."
        )
    return target


def validate_staging_database_urls(
    environment: Mapping[str, str] = os.environ,
    *,
    require_admin: bool = True,
) -> tuple[DatabaseTarget, DatabaseTarget | None]:
    app_url = required_environment(environment, "PICAFRESA_STAGING_DATABASE_URL")
    allowed_host = required_environment(environment, "PICAFRESA_STAGING_DATABASE_HOST")
    production_host = required_environment(environment, "PICAFRESA_PRODUCTION_DATABASE_HOST")
    app = parse_database_url(
        app_url,
        variable_name="PICAFRESA_STAGING_DATABASE_URL",
    )

    if app.host != allowed_host:
        raise ImproperlyConfigured(
            "PICAFRESA_STAGING_DATABASE_URL host does not match PICAFRESA_STAGING_DATABASE_HOST."
        )
    if app.host in {None, "localhost", "127.0.0.1", "::1"}:
        raise ImproperlyConfigured(
            "PICAFRESA_STAGING_DATABASE_URL must use the configured staging server."
        )
    if app.database != STAGING_DATABASE_NAME or app.role != STAGING_DATABASE_ROLE:
        raise ImproperlyConfigured(
            "PICAFRESA_STAGING_DATABASE_URL must use database "
            f"{STAGING_DATABASE_NAME} and role {STAGING_DATABASE_ROLE}."
        )

    if app.host == production_host:
        raise ImproperlyConfigured(
            "The staging database server matches the configured production server."
        )

    if not require_admin:
        return app, None

    admin_url = required_environment(
        environment,
        "PICAFRESA_STAGING_DATABASE_ADMIN_URL",
    )
    admin = parse_database_url(
        admin_url,
        variable_name="PICAFRESA_STAGING_DATABASE_ADMIN_URL",
    )
    if (admin.host, admin.port) != (app.host, app.port):
        raise ImproperlyConfigured(
            "The staging admin and application URLs must target the same server."
        )
    if admin.role == app.role:
        raise ImproperlyConfigured(
            "PICAFRESA_STAGING_DATABASE_ADMIN_URL must use a separate provisioning role."
        )
    return app, admin


def provision_local_database(postgres_directory: Path) -> str:
    from pgembed.postgres_server import get_server

    server = get_server(postgres_directory)
    admin_url = server.get_uri()
    app_url = database_url_with_identity(
        admin_url,
        role=LOCAL_DATABASE_ROLE,
        database=LOCAL_DATABASE_NAME,
    )
    validate_local_database_url(app_url)
    provision_database(admin_url, app_url)
    return app_url


def provision_staging_database(
    environment: Mapping[str, str] = os.environ,
) -> str:
    app, admin = validate_staging_database_urls(environment)
    assert admin is not None
    provision_database(admin.url, app.url)
    return app.url


def provision_database(admin_url: str, app_url: str) -> None:
    app = parse_database_url(app_url, variable_name="application database URL")
    admin = parse_database_url(admin_url, variable_name="admin database URL")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        _require_supported_postgres(connection)
        connection.execute(
            "SELECT pg_advisory_lock(hashtext(%s))",
            (f"picafresa-provision:{app.database}",),
        )
        unexpected_databases = connection.execute(
            """
            SELECT datname
            FROM pg_database
            WHERE datallowconn
              AND datname <> ALL(%s)
            """,
            (
                [
                    app.database,
                    "postgres",
                    "template0",
                    "template1",
                    "test_postgres",
                ],
            ),
        ).fetchall()
        if unexpected_databases:
            names = ", ".join(row[0] for row in unexpected_databases)
            raise RuntimeError(
                "Provisioning requires a dedicated local or staging PostgreSQL server; "
                f"found other databases: {names}."
            )

        role_exists = connection.execute(
            "SELECT EXISTS (SELECT FROM pg_roles WHERE rolname = %s)",
            (app.role,),
        ).fetchone()
        assert role_exists is not None
        if not role_exists[0]:
            connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(app.role)))
        connection.execute(
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(app.role))
        )
        if app.password:
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(app.role)),
                (app.password,),
            )

        database_exists = connection.execute(
            "SELECT EXISTS (SELECT FROM pg_database WHERE datname = %s)",
            (app.database,),
        ).fetchone()
        assert database_exists is not None
        if not database_exists[0]:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(app.database)))
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(app.database))
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(app.database),
                sql.Identifier(app.role),
            )
        )
        other_databases = connection.execute(
            """
            SELECT datname
            FROM pg_database
            WHERE datallowconn
              AND datname <> %s
            """,
            (app.database,),
        ).fetchall()
        for (database_name,) in other_databases:
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(admin.role),
                )
            )
            connection.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database_name)
                )
            )

    target_admin_url = database_url_with_identity(admin_url, database=app.database)
    with psycopg.connect(target_admin_url, autocommit=True) as connection:
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute(
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(app.role))
        )


def verify_database(url: str, *, environment: str) -> DatabaseReport:
    if environment == "local":
        validate_local_database_url(url)
    elif environment == "staging":
        validate_staging_database_urls(
            {
                "PICAFRESA_STAGING_DATABASE_URL": url,
                "PICAFRESA_STAGING_DATABASE_HOST": urlparse(url).hostname or "",
            },
            require_admin=False,
        )
    else:
        raise ValueError(f"Unsupported environment: {environment}")

    with psycopg.connect(url) as connection:
        major_version = _require_supported_postgres(connection)
        row = connection.execute(
            """
            SELECT
                current_database(),
                current_user,
                role.rolsuper,
                role.rolcreatedb,
                role.rolcreaterole,
                database.datdba = role.oid,
                has_schema_privilege(current_user, 'public', 'CREATE'),
                EXISTS (
                    SELECT 1
                    FROM pg_database AS other_database
                    WHERE other_database.datallowconn
                      AND other_database.datname <> current_database()
                      AND has_database_privilege(
                          current_user,
                          other_database.datname,
                          'CONNECT'
                      )
                )
            FROM pg_roles AS role
            JOIN pg_database AS database
              ON database.datname = current_database()
            WHERE role.rolname = current_user
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("Could not inspect the PostgreSQL application role.")
        report = DatabaseReport(
            database=row[0],
            role=row[1],
            postgres_major_version=major_version,
            is_superuser=row[2],
            can_create_database=row[3],
            can_create_role=row[4],
            owns_database=row[5],
            can_create_in_public_schema=row[6],
            can_connect_other_databases=row[7],
        )
        _require_least_privilege(report)
        return report


def _require_supported_postgres(
    connection: psycopg.Connection[tuple[object, ...]],
) -> int:
    row = connection.execute("SHOW server_version_num").fetchone()
    assert row is not None
    major_version = int(str(row[0])) // 10_000
    if major_version != POSTGRES_MAJOR_VERSION:
        raise RuntimeError(
            f"PostgreSQL {POSTGRES_MAJOR_VERSION} is required; found {major_version}."
        )
    return major_version


def _require_least_privilege(report: DatabaseReport) -> None:
    if (
        report.is_superuser
        or report.can_create_database
        or report.can_create_role
        or report.owns_database
        or report.can_connect_other_databases
        or not report.can_create_in_public_schema
    ):
        raise RuntimeError(
            f"Role {report.role} does not have the required least-privilege configuration."
        )


def database_url_with_identity(
    url: str,
    *,
    role: str | None = None,
    database: str | None = None,
) -> str:
    parsed = urlparse(url)
    username = quote(role or unquote(parsed.username or ""), safe="")
    password = parsed.password
    userinfo = username
    if password is not None:
        userinfo += f":{password}"
    hostname = parsed.hostname
    netloc = f"{userinfo}@"
    if hostname:
        formatted_host = f"[{hostname}]" if ":" in hostname else hostname
        netloc += formatted_host
        if parsed.port is not None:
            netloc += f":{parsed.port}"
    path = f"/{quote(database or unquote(parsed.path.removeprefix('/')), safe='')}"
    return urlunparse(parsed._replace(netloc=netloc, path=path))
