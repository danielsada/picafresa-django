from .base import *  # noqa: F403
from .embedded_postgres import admin_database_url
from .environment import database_from_url

DEBUG = False
SECRET_KEY = "test-only"
GOVERNMENT_IDENTIFIER_LOOKUP_KEY = "test-government-identifier-lookup-only"
ALLOWED_HOSTS = ["testserver"]
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    },
}

DATABASES = {"default": database_from_url(admin_database_url())}
