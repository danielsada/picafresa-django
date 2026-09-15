from .base import *  # noqa: F403
from .environment import database_from_url, required_environment

DEBUG = False
SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
GOVERNMENT_IDENTIFIER_LOOKUP_KEY = required_environment("GOVERNMENT_IDENTIFIER_LOOKUP_KEY")
ALLOWED_HOSTS = required_environment("DJANGO_ALLOWED_HOSTS").split(",")

DATABASES = {
    "default": database_from_url(
        required_environment("PICAFRESA_PRODUCTION_DATABASE_URL"),
        require_ssl=True,
    ),
}

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_SSL_REDIRECT = True
