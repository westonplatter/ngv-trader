"""Token management endpoints.

The point of these tests is the negative assertion: no response from any
endpoint may contain the token value. The API encrypts on write and never
decrypts on read.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.main import app
from src.utils import crypto

TOKEN_VALUE = "flex-token-from-the-ui"  # noqa: S105  # nosec B105 — fixture value, not a credential
REPLACEMENT = "flex-token-replacement"  # noqa: S105  # nosec B105


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV_VAR, crypto.generate_key())
    crypto.reset_cache()
    yield
    crypto.reset_cache()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clean_tokens(engine: Engine) -> None:
    """Endpoints commit, so clear the table around each test."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE accounts SET flex_query_token_id = NULL"))
        conn.execute(text("DELETE FROM flexquery_tokens"))
    yield
    with engine.begin() as conn:
        conn.execute(text("UPDATE accounts SET flex_query_token_id = NULL"))
        conn.execute(text("DELETE FROM flexquery_tokens"))


def _create(client: TestClient, name: str = "main", token: str = TOKEN_VALUE) -> dict:
    resp = client.post(
        "/api/v1/flexquery-tokens",
        json={"name": name, "report_id": "633891", "token": token},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_returns_metadata_without_the_token(client: TestClient) -> None:
    body = _create(client)
    assert body["name"] == "main"
    assert body["report_id"] == "633891"
    assert body["is_active"] is True
    assert body["account_count"] == 0
    assert TOKEN_VALUE not in str(body)
    assert "token" not in body


def test_create_stores_ciphertext(client: TestClient, engine: Engine) -> None:
    body = _create(client)
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT token_encrypted FROM flexquery_tokens WHERE id = :id"),
            {"id": body["id"]},
        ).scalar_one()
    assert stored != TOKEN_VALUE
    assert crypto.decrypt(stored) == TOKEN_VALUE


def test_list_never_returns_the_token(client: TestClient) -> None:
    _create(client)
    resp = client.get("/api/v1/flexquery-tokens")
    assert resp.status_code == 200
    assert TOKEN_VALUE not in resp.text


def test_duplicate_name_is_a_conflict(client: TestClient) -> None:
    _create(client)
    resp = client.post(
        "/api/v1/flexquery-tokens",
        json={"name": "main", "report_id": "1", "token": "x"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_rename_leaves_the_token_alone(client: TestClient, engine: Engine) -> None:
    body = _create(client)
    resp = client.patch(f"/api/v1/flexquery-tokens/{body['id']}", json={"name": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT token_encrypted FROM flexquery_tokens WHERE id = :id"),
            {"id": body["id"]},
        ).scalar_one()
    assert crypto.decrypt(stored) == TOKEN_VALUE


def test_blank_token_on_update_leaves_it_alone(client: TestClient, engine: Engine) -> None:
    """The edit form submits an empty token field to mean 'unchanged'."""
    body = _create(client)
    resp = client.patch(f"/api/v1/flexquery-tokens/{body['id']}", json={"token": "   "})
    assert resp.status_code == 200

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT token_encrypted FROM flexquery_tokens WHERE id = :id"),
            {"id": body["id"]},
        ).scalar_one()
    assert crypto.decrypt(stored) == TOKEN_VALUE


def test_supplying_a_token_replaces_it(client: TestClient, engine: Engine) -> None:
    body = _create(client)
    resp = client.patch(f"/api/v1/flexquery-tokens/{body['id']}", json={"token": REPLACEMENT})
    assert resp.status_code == 200
    assert REPLACEMENT not in resp.text

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT token_encrypted FROM flexquery_tokens WHERE id = :id"),
            {"id": body["id"]},
        ).scalar_one()
    assert crypto.decrypt(stored) == REPLACEMENT


def test_deactivate_via_patch(client: TestClient) -> None:
    body = _create(client)
    resp = client.patch(f"/api/v1/flexquery-tokens/{body['id']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_update_missing_token_is_404(client: TestClient) -> None:
    assert client.patch("/api/v1/flexquery-tokens/999999", json={"name": "x"}).status_code == 404


def test_create_without_an_encryption_key_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 500 traceback here would echo the bind parameters, token included."""
    monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV_VAR, raising=False)
    crypto.reset_cache()

    resp = client.post(
        "/api/v1/flexquery-tokens",
        json={"name": "main", "report_id": "1", "token": TOKEN_VALUE},
    )

    assert resp.status_code == 503
    assert crypto.ENCRYPTION_KEY_ENV_VAR in resp.json()["detail"]
    assert TOKEN_VALUE not in resp.text
