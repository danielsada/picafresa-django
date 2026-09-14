from pathlib import Path

import psutil
from pgembed.postgres_server import PostgresServer, get_server

PROJECT_DIR = Path(__file__).resolve().parents[2]
POSTGRES_DIR = PROJECT_DIR / ".local" / "postgres"
POSTGRES_SERVER: PostgresServer | None = None


def database_url() -> str:
    global POSTGRES_SERVER
    if POSTGRES_SERVER is None:
        POSTGRES_DIR.parent.mkdir(parents=True, exist_ok=True)
        POSTGRES_SERVER = get_server(POSTGRES_DIR)
    return POSTGRES_SERVER.get_uri()


def cleanup() -> None:
    global POSTGRES_SERVER
    if POSTGRES_SERVER is not None:
        handles = POSTGRES_SERVER.global_process_id_list
        handles.put([pid for pid in handles.get() if psutil.pid_exists(pid)])
        POSTGRES_SERVER.cleanup()
        POSTGRES_SERVER = None
