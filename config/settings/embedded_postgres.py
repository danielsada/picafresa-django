from pathlib import Path

import psutil
from pgembed.postgres_server import PostgresServer, get_server

from config.postgres import provision_local_database

PROJECT_DIR = Path(__file__).resolve().parents[2]
POSTGRES_DIR = PROJECT_DIR / ".local" / "postgres"
POSTGRES_SERVER: PostgresServer | None = None
DATABASE_URL: str | None = None


def _ensure_server() -> PostgresServer:
    global DATABASE_URL, POSTGRES_SERVER
    if POSTGRES_SERVER is None:
        POSTGRES_DIR.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = provision_local_database(POSTGRES_DIR)
        POSTGRES_SERVER = get_server(POSTGRES_DIR)
    return POSTGRES_SERVER


def database_url() -> str:
    _ensure_server()
    assert DATABASE_URL is not None
    return DATABASE_URL


def admin_database_url() -> str:
    return _ensure_server().get_uri()


def cleanup() -> None:
    global DATABASE_URL, POSTGRES_SERVER
    if POSTGRES_SERVER is not None:
        handles = POSTGRES_SERVER.global_process_id_list
        handles.put([pid for pid in handles.get() if psutil.pid_exists(pid)])
        POSTGRES_SERVER.cleanup()
        POSTGRES_SERVER = None
        DATABASE_URL = None
