#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export DJANGO_SETTINGS_MODULE=config.settings.local

uv run manage.py migrate --noinput
uv run manage.py seed_local_demo
exec uv run manage.py runserver 127.0.0.1:8000 --noreload
