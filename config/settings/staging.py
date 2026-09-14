from .base import *  # noqa: F403
from .environment import database_from_url, required_environment

DEBUG = False
SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = required_environment("DJANGO_ALLOWED_HOSTS").split(",")

DATABASES = {
    "default": database_from_url(
        required_environment("PICAFRESA_STAGING_DATABASE_URL"),
        require_ssl=True,
    ),
}
