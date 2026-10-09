import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database, connect
from app.main import create_app
from app.migrate import apply_migrations
from app.users import create_user
from tests.helpers import GOOD_PASSWORD, GUARD_HEADERS


@pytest.fixture
def conn(tmp_path):
    """A migrated, empty database in a temporary directory."""
    c = connect(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def settings():
    # Minimal argon2 cost so the suite stays fast; the real defaults are covered in test_config.
    return Settings.from_env({"ARGON2_MEMORY_KIB": "8", "ARGON2_TIME_COST": "1"})


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    setup = connect(path)
    apply_migrations(setup)
    setup.close()
    database = Database(path, readers=2)
    yield database
    database.close()


@pytest.fixture
def app(settings, db):
    return create_app(settings, db)


@pytest.fixture
def client(app):
    with TestClient(app, headers=GUARD_HEADERS) as c:
        yield c


@pytest.fixture
def make_user(app, db):
    def _make(username="amina", password=GOOD_PASSWORD, role="member"):
        return create_user(db, app.state.passwords, username, password, role)

    return _make


@pytest.fixture
def login_as(app, make_user):
    """Create a user and return a logged-in client for them (one client per user)."""
    from tests.helpers import login

    def _login_as(username, role="member"):
        make_user(username, role=role)
        c = TestClient(app, headers=GUARD_HEADERS)
        assert login(c, username).status_code == 200
        return c

    return _login_as
