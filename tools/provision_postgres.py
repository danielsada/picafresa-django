#!/usr/bin/env python
import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

from config.postgres import (  # noqa: E402
    provision_local_database,
    provision_staging_database,
    shared_staging_server_allowed,
    validate_staging_database_urls,
    verify_database,
)

LOCAL_POSTGRES_DIR = PROJECT_DIR / ".local" / "postgres"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Provision or verify Picafresa PostgreSQL environments."
    )
    parser.add_argument(
        "command",
        choices=(
            "provision-local",
            "verify-local",
            "provision-staging",
            "verify-staging",
        ),
    )
    args = parser.parse_args()

    try:
        if args.command in {"provision-local", "verify-local"}:
            url = provision_local_database(LOCAL_POSTGRES_DIR)
            report = verify_database(url, environment="local")
        elif args.command == "provision-staging":
            url = provision_staging_database()
            report = verify_database(
                url,
                environment="staging",
                allow_other_database_connections=shared_staging_server_allowed(),
            )
        else:
            app, _ = validate_staging_database_urls(require_admin=False)
            report = verify_database(
                app.url,
                environment="staging",
                allow_other_database_connections=shared_staging_server_allowed(),
            )
    except (ImproperlyConfigured, OSError, RuntimeError) as error:
        parser.exit(1, f"PostgreSQL setup failed: {error}\n")

    print(
        f"PostgreSQL {report.postgres_major_version} verified: "
        f"database={report.database}, role={report.role}, least_privilege=yes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
