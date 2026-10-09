import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_make_run_loads_env_file_and_prod_guard_fires(tmp_path):
    env_file = tmp_path / "prod.env"
    env_file.write_text("APP_ENV=prod\nSESSION_SECRET=\n")
    result = subprocess.run(  # noqa: S603
        ["make", "run", f"ENV_FILE={env_file}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stdout + result.stderr
