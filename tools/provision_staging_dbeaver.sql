/*
Picafresa staging PostgreSQL provisioning for DBeaver
=====================================================

Requirements:
- PostgreSQL 18 on the shared Azure PostgreSQL server.
- An administrator role with CREATEROLE and CREATEDB (or superuser).
- DBeaver configured to execute statements with auto-commit enabled.

Important:
- Never run this against the production server.
- Do not save a real password in this file.
- Execute STAGE 1 while connected to the "postgres" database.
- Then reconnect DBeaver to "picafresa_staging" and execute STAGE 2 only.
*/


/* -------------------------------------------------------------------------
STAGE 1: Run on the shared server, connected to database "postgres"
------------------------------------------------------------------------- */

DO $guard$
DECLARE
    server_major_version integer := current_setting('server_version_num')::integer / 10000;
BEGIN
    IF server_major_version <> 18 THEN
        RAISE EXCEPTION
            'PostgreSQL 18 is required; connected server is PostgreSQL %.',
            server_major_version;
    END IF;

    IF NOT (
        SELECT rolsuper OR (rolcreatedb AND rolcreaterole)
        FROM pg_roles
        WHERE rolname = current_user
    ) THEN
        RAISE EXCEPTION
            'Current role % must be a superuser or have CREATEDB and CREATEROLE.',
            current_user;
    END IF;

END
$guard$;

DO $role$
DECLARE
    generated_password text :=
        replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'picafresa_staging_app'
    ) THEN
        CREATE ROLE picafresa_staging_app;
    END IF;

    EXECUTE format(
        'ALTER ROLE %I WITH LOGIN PASSWORD %L',
        'picafresa_staging_app',
        generated_password
    );

    ALTER ROLE picafresa_staging_app
        WITH
        NOSUPERUSER
        NOCREATEDB
        NOCREATEROLE
        NOINHERIT
        NOREPLICATION
        NOBYPASSRLS;

    RAISE NOTICE
        'Save this picafresa_staging_app password in the staging secret store: %',
        generated_password;
END
$role$;

/*
CREATE DATABASE cannot run inside a transaction or conditional DO block.
Run this statement once. If picafresa_staging already exists, skip it.
The administrator intentionally remains the database owner.
*/
CREATE DATABASE picafresa_staging;

REVOKE ALL ON DATABASE picafresa_staging FROM PUBLIC;
GRANT CONNECT ON DATABASE picafresa_staging TO picafresa_staging_app;

/*
This is a shared server. Do not revoke PUBLIC privileges from postgres,
template1, azure_maintenance, azure_sys, picafresadb, watolls, or any other
database: doing so could break their existing users.

Remove any role-specific database grants previously assigned to the staging
role. PostgreSQL may still permit connection through PUBLIC, but this role
receives no object privileges in those databases. PostgreSQL has no per-role
DENY that can override PUBLIC.
*/
DO $database_grants$
DECLARE
    other_database record;
BEGIN
    FOR other_database IN
        SELECT datname
        FROM pg_database
        WHERE datname <> 'picafresa_staging'
    LOOP
        EXECUTE format(
            'REVOKE ALL ON DATABASE %I FROM picafresa_staging_app',
            other_database.datname
        );
    END LOOP;
END
$database_grants$;

SELECT
    role.rolname,
    role.rolsuper,
    role.rolcreatedb,
    role.rolcreaterole,
    role.rolinherit,
    has_database_privilege(role.rolname, 'picafresa_staging', 'CONNECT')
        AS can_connect_staging
FROM pg_roles AS role
WHERE role.rolname = 'picafresa_staging_app';

/*
Expected:
- rolsuper, rolcreatedb, rolcreaterole, rolinherit: false
- can_connect_staging: true
*/


/* -------------------------------------------------------------------------
STAGE 2: Reconnect DBeaver to database "picafresa_staging", then run below
------------------------------------------------------------------------- */

DO $guard$
BEGIN
    IF current_database() <> 'picafresa_staging' THEN
        RAISE EXCEPTION
            'Connect DBeaver to picafresa_staging before running STAGE 2.';
    END IF;
END
$guard$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO picafresa_staging_app;

SELECT
    current_database() AS database_name,
    has_schema_privilege(
        'picafresa_staging_app',
        'public',
        'USAGE'
    ) AS has_schema_usage,
    has_schema_privilege(
        'picafresa_staging_app',
        'public',
        'CREATE'
    ) AS can_create_django_tables;

/*
Expected:
- database_name: picafresa_staging
- has_schema_usage: true
- can_create_django_tables: true

After this script succeeds, configure PICAFRESA_STAGING_DATABASE_URL with the
picafresa_staging_app password and run:

    DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py migrate
    DJANGO_SETTINGS_MODULE=config.settings.staging uv run manage.py check --deploy
*/
