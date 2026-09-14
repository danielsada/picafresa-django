import os

from .base import *  # noqa: F403
from .embedded_postgres import database_url
from .environment import database_from_url

DEBUG = True
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only")
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

DATABASES = {
    "default": database_from_url(
        os.environ.get("PICAFRESA_LOCAL_DATABASE_URL") or database_url(),
    ),
}
