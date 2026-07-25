"""Faz 0 kabul testi: /health çalışıyor ve DB durumunu gerçekten raporluyor."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_yanit_bicimi() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "db"}
    assert isinstance(body["db"], bool)
    assert body["status"] in {"ok", "degraded"}


def test_health_db_bagli() -> None:
    """DB ayakta olmalı. Kırmızıysa önce `docker compose up -d` çalıştır."""
    body = client.get("/health").json()
    assert body["db"] is True, "PostgreSQL'e bağlanılamadı"
    assert body["status"] == "ok"
