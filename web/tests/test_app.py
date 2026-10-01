from app import create_app


def test_index():
    client = create_app().test_client()
    assert client.get("/").status_code == 200


def test_chat_sends_history_and_keeps_category(tmp_path, monkeypatch):
    """두 번째 질문부터 이전 대화(고객/AI)가 AI 서버로 가고, 분야 없는 응답(인사 등)이 기존 분야를 지우지 않는다."""
    from app.extensions import db
    from app.models import Consult

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")  # 로컬 개발 DB 대신 임시 DB
    app = create_app()
    client = app.test_client()

    replies = [
        {"answer": "앱에서 가능해요", "category": "은행", "topic": "대출", "confidence": 1.0},
        {"answer": "도움이 되었다니 기쁩니다", "category": None, "confidence": 0.0},
    ]
    sent = []

    def fake_ask(session_id, message, history=None):
        sent.append(history)
        return dict(replies[len(sent) - 1])

    monkeypatch.setattr("app.routes.chat.ai_client.ask", fake_ask)

    client.post("/api/chat", json={"message": "대출 연장하고 싶어요"})
    result = client.post("/api/chat", json={"message": "감사합니다"}).get_json()

    assert sent[0] == []
    assert sent[1] == [{"role": "user", "content": "대출 연장하고 싶어요"}, {"role": "assistant", "content": "앱에서 가능해요"}]
    with app.app_context():
        assert db.session.get(Consult, result["consult_id"]).category == "은행"
