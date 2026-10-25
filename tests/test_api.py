from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_vk_confirmation(monkeypatch):
    monkeypatch.setenv("VK_CONFIRMATION", "confirm-token")
    monkeypatch.setenv("VK_EVENT_MODE", "callback")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post("/vk/callback", json={"type": "confirmation"})
        assert response.status_code == 200
        assert response.text == "confirm-token"
    get_settings.cache_clear()


def test_vk_callback_ignored_in_longpoll_mode(monkeypatch):
    monkeypatch.setenv("VK_EVENT_MODE", "longpoll")
    monkeypatch.setenv("VK_TOKEN", "")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post(
            "/vk/callback",
            json={"type": "message_new", "object": {"message": {"from_id": 1, "peer_id": 1, "text": "hi"}}},
        )
        assert response.status_code == 200
        assert response.text == "ok"
    get_settings.cache_clear()
