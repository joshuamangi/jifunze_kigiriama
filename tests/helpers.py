GOOD_PASSWORD = "correct horse battery"  # noqa: S105 - test fixture
GUARD_HEADERS = {"X-Requested-With": "jifunze"}


def login(client, username="amina", password=GOOD_PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})
