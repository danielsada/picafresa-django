import os

from config.postgres import validate_staging_database_urls

from .base import *  # noqa: F403
from .environment import database_from_url, required_environment

DEBUG = False
SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
GOVERNMENT_IDENTIFIER_LOOKUP_KEY = required_environment("GOVERNMENT_IDENTIFIER_LOOKUP_KEY")
ALLOWED_HOSTS = required_environment("DJANGO_ALLOWED_HOSTS").split(",")

STAGING_DATABASE, _ = validate_staging_database_urls(os.environ, require_admin=False)
DATABASES = {"default": database_from_url(STAGING_DATABASE.url, require_ssl=True)}
