from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.postgres import (
    LOCAL_DATABASE_NAME,
    LOCAL_DATABASE_ROLE,
    provision_local_database,
    validate_local_database_url,
    validate_staging_database_urls,
    verify_database,
)


def test_local_database_can_be_provisioned_and_verified_without_container(
    tmp_path: Path,
) -> None:
    database_url = provision_local_database(tmp_path / "postgres")

    report = verify_database(database_url, environment="local")

    assert report.database == LOCAL_DATABASE_NAME
    assert report.role == LOCAL_DATABASE_ROLE
    assert report.postgres_major_version == 17
    assert report.is_superuser is False
    assert report.can_create_database is False
    assert report.can_create_role is False
    assert report.owns_database is False
    assert report.can_create_in_public_schema is True
    assert report.can_connect_other_databases is False


def test_local_database_rejects_remote_target() -> None:
    with pytest.raises(
        ImproperlyConfigured,
        match="PICAFRESA_LOCAL_DATABASE_URL must use a local PostgreSQL host",
    ):
        validate_local_database_url(
            "postgresql://picafresa_local_app:secret@production.example/picafresa_local"
        )


def test_local_database_rejects_query_parameter_host_override() -> None:
    with pytest.raises(
        ImproperlyConfigured,
        match="PICAFRESA_LOCAL_DATABASE_URL must use a local PostgreSQL host",
    ):
        validate_local_database_url(
            "postgresql://picafresa_local_app@localhost/picafresa_local?host=production.example"
        )


def test_staging_database_requires_secret_configuration() -> None:
    with pytest.raises(
        ImproperlyConfigured,
        match="Set the PICAFRESA_STAGING_DATABASE_URL environment variable",
    ):
        validate_staging_database_urls({})


def test_staging_database_rejects_production_target() -> None:
    environment = {
        "PICAFRESA_STAGING_DATABASE_URL": (
            "postgresql://picafresa_staging_app:secret@db.example/picafresa_staging?sslmode=require"
        ),
        "PICAFRESA_STAGING_DATABASE_ADMIN_URL": (
            "postgresql://staging_admin:secret@db.example/postgres?sslmode=require"
        ),
        "PICAFRESA_STAGING_DATABASE_HOST": "db.example",
        "PICAFRESA_PRODUCTION_DATABASE_HOST": "db.example",
        "PICAFRESA_PRODUCTION_DATABASE_URL": (
            "postgresql://picafresa_production_app:secret@db.example/"
            "picafresa_staging?sslmode=require"
        ),
    }

    with pytest.raises(
        ImproperlyConfigured,
        match="staging database server matches the configured production server",
    ):
        validate_staging_database_urls(environment)


def test_staging_database_rejects_query_parameter_host_override() -> None:
    environment = {
        "PICAFRESA_STAGING_DATABASE_URL": (
            "postgresql://picafresa_staging_app:secret@staging.example/"
            "picafresa_staging?host=production.example&sslmode=require"
        ),
        "PICAFRESA_STAGING_DATABASE_ADMIN_URL": (
            "postgresql://staging_admin:secret@staging.example/postgres?sslmode=require"
        ),
        "PICAFRESA_STAGING_DATABASE_HOST": "staging.example",
        "PICAFRESA_PRODUCTION_DATABASE_HOST": "production.example",
    }

    with pytest.raises(
        ImproperlyConfigured,
        match="host does not match PICAFRESA_STAGING_DATABASE_HOST",
    ):
        validate_staging_database_urls(environment)
