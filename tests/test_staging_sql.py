from pathlib import Path


def test_dbeaver_script_is_safe_for_shared_staging_server() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "tools" / "provision_staging_dbeaver.sql"
    ).read_text()

    assert "Unexpected databases" not in script
    assert "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC" not in script
    assert "REVOKE CONNECT ON DATABASE template1 FROM PUBLIC" not in script
