from fastapi.testclient import TestClient

from pricefinder.api import app as api_module


def test_health_and_providers(monkeypatch, repo):
    monkeypatch.setattr(api_module, "_repo", repo)
    client = TestClient(api_module.app)
    assert client.get("/health").json()["ok"] is True
    names = {p["name"] for p in client.get("/providers").json()}
    assert "mock" in names


def test_search_endpoint(monkeypatch, repo):
    monkeypatch.setattr(api_module, "_repo", repo)
    client = TestClient(api_module.app)
    r = client.post("/search", json={"text": "nintendo switch oled", "providers": ["mock"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offers"] and body["providers_queried"] == ["mock"]
