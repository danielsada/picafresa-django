import os
import signal
import subprocess
import sys
from pathlib import Path
from types import FrameType
from typing import Never

from pgembed.postgres_server import get_server

PROJECT_DIR = Path(__file__).resolve().parents[1]
POSTGRES_DIR = PROJECT_DIR / ".local" / "postgres"


def request_shutdown(signal_number: int, _frame: FrameType | None) -> Never:
    raise SystemExit(128 + signal_number)


def run_manage_py(*arguments: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, PROJECT_DIR / "manage.py", *arguments],
        cwd=PROJECT_DIR,
        env=environment,
        check=True,
    )


def main() -> None:
    POSTGRES_DIR.parent.mkdir(parents=True, exist_ok=True)
    server = get_server(POSTGRES_DIR)
    signal.signal(signal.SIGTERM, request_shutdown)
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "config.settings.local"
    environment["PICAFRESA_LOCAL_DATABASE_URL"] = server.get_uri()

    try:
        run_manage_py("migrate", environment=environment)
        address = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:8000"
        run_manage_py("runserver", address, "--noreload", environment=environment)
    finally:
        server.cleanup()


if __name__ == "__main__":
    main()
