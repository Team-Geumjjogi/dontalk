from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_chat_mock():
    r = client.post("/chat", json={"session_id": "t1", "message": "대출 만기 연장하고 싶어요"})
    assert r.status_code == 200
    assert "answer" in r.json()
