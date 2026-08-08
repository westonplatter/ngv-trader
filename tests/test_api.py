"""API smoke tests — catches FastAPI/pydantic/starlette breakage on bumps."""

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from src.api.main import app


def test_health_reports_database_connected(engine: Engine) -> None:
    with TestClient(app) as client:
        body = client.get("/api/v1/health").json()
    assert body == {"status": "ok", "database": "connected"}


def test_openapi_schema_builds(engine: Engine) -> None:
    """Every route's response model must still be serializable."""
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/v1/positions" in resp.json()["paths"]
