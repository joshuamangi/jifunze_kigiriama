import pytest

from app.db import connect
from app.migrate import apply_migrations


@pytest.fixture
def conn(tmp_path):
    """A migrated, empty database in a temporary directory."""
    c = connect(tmp_path / "test.db")
    apply_migrations(c)
    yield c
    c.close()
