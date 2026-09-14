import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise ImproperlyConfigured(f"Set the {name} environment variable.")
    return value


def database_from_url(url: str, *, require_ssl: bool = False) -> dj_database_url.DBConfig:
    return dj_database_url.parse(
        url,
        conn_max_age=60,
        conn_health_checks=True,
        ssl_require=require_ssl,
    )
