from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_healthz_returns_ok():
    client = TestClient(create_app(Settings.from_env({})))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
