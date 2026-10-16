"""Runs tests/js/web_behaviour.mjs: how the PWA's api.js and service worker behave when the network
fails or Cloudflare Access redirects to its login. Skipped when Node is not installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "js" / "web_behaviour.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node to run the JS")


def test_pwa_network_failure_behaviour():
    result = subprocess.run(  # noqa: S603 - fixed argv, our own script
        ["node", str(SCRIPT)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok   " in result.stdout
