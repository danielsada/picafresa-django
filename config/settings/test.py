from .base import *  # noqa: F403
from .embedded_postgres import admin_database_url
from .environment import database_from_url

DEBUG = False
SECRET_KEY = "test-only"
ALLOWED_HOSTS = ["testserver"]

DATABASES = {"default": database_from_url(admin_database_url())}
