import os

from config.postgres import validate_local_database_url

from .base import *  # noqa: F403
from .embedded_postgres import database_url
from .environment import database_from_url

DEBUG = True
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only")
GOVERNMENT_IDENTIFIER_LOOKUP_KEY = os.environ.get(
    "GOVERNMENT_IDENTIFIER_LOOKUP_KEY",
    "local-government-identifier-lookup-only",
)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

LOCAL_DATABASE_URL = os.environ.get("PICAFRESA_LOCAL_DATABASE_URL") or database_url()
validate_local_database_url(LOCAL_DATABASE_URL)
DATABASES = {"default": database_from_url(LOCAL_DATABASE_URL)}
