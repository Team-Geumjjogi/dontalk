"""고객 플로우: 채팅 -> 상담 종료/상담사 연결 -> 만족도(1회) -> 세션 정리."""
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import Consult, ConsultStatus, HandoffReason, Message, Satisfaction

SOURCES = [{"doc_id": "q1", "category": "은행", "topic": "대출", "score": 0.8, "snippet": "만기 연장?",
            "follow_up_question": "추가 서류는?", "output": "종합 답변"}]


@pytest.fixture
def ai(monkeypatch):
    """AI 서버 응답을 바꿔 끼울 수 있게 한다. ai.reply 를 수정해서 쓴다."""
    class FakeAi:
        reply = {"answer": "답변", "category": "은행", "topic": "대출", "confidence": 1.0, "sources": SOURCES}

    monkeypatch.setattr("app.routes.chat.ai_client.ask", lambda sid, msg, history=None: dict(FakeAi.reply))
    return FakeAi


def only_consult(app) -> SimpleNamespace:
    """DB에 있는 유일한 상담의 값을 읽어 돌려준다 (세션이 닫힌 뒤에도 쓸 수 있게 필요한 값만 복사)."""
    with app.app_context():
        c = db.session.scalars(db.select(Consult)).one()
        return SimpleNamespace(
            status=c.status, category=c.category, ai_category=c.ai_category, satisfaction=c.satisfaction,
            handoff_reason=c.handoff_reason, handoff_detail=c.handoff_detail, handoff_at=c.handoff_at,
            closed_at=c.closed_at, customer_name=c.customer.name, message_count=len(c.messages),
        )


def test_chat_creates_consult_and_stores_sources(app, client, ai):
    client.post("/api/chat", json={"message": "대출 연장"})
    with app.app_context():
        consult = db.session.scalars(db.select(Consult)).one()
        assert consult.status == ConsultStatus.chatting and consult.category == "은행"
        assert [m.sender.value for m in consult.messages] == ["customer", "ai"]
        assert consult.messages[1].sources[0]["follow_up_question"] == "추가 서류는?"


@pytest.mark.parametrize("code,expected", [
    ("contact_request", HandoffReason.customer_request), ("action_request", HandoffReason.action_request),
    ("no_basis", HandoffReason.no_basis), ("low_confidence", HandoffReason.low_confidence), ("ai_error", HandoffReason.ai_error),
])
def test_ai_handoff_code_maps_to_reason(app, client, ai, code, expected):
    ai.reply = {"answer": "연결해 드릴게요", "handoff_needed": True, "handoff_code": code, "handoff_reason": "상세 사유"}
    client.post("/api/chat", json={"message": "질문"})
    consult = only_consult(app)
    assert consult.handoff_reason == expected and consult.handoff_detail == "상세 사유"


def test_end_then_feedback_once(app, client, ai):
    client.post("/api/chat", json={"message": "질문"})
    assert client.post("/api/end").get_json()["status"] == "ended"
    assert client.post("/api/feedback", json={"satisfied": True}).get_json() == {"offer_handoff": False}
    client.post("/api/feedback", json={"satisfied": False})  # 두 번째 평가는 무시된다
    consult = only_consult(app)
    assert consult.satisfaction == Satisfaction.satisfied and consult.closed_at is not None


def test_feedback_skip_records_nothing(app, client, ai):
    client.post("/api/chat", json={"message": "질문"})
    client.post("/api/end")
    assert client.post("/api/feedback", json={"satisfied": None}).get_json() == {"offer_handoff": False}
    assert only_consult(app).satisfaction is None


def test_dissatisfied_after_end_offers_handoff_and_records_reason(app, client, ai):
    client.post("/api/chat", json={"message": "질문"})
    client.post("/api/end")
    assert client.post("/api/feedback", json={"satisfied": False}).get_json() == {"offer_handoff": True}
    response = client.post("/api/handoff", json={"name": "홍길동"})
    assert response.status_code == 200
    consult = only_consult(app)
    assert consult.status in (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day)
    assert consult.handoff_reason == HandoffReason.user_dissatisfied
    assert consult.ai_category == "은행" and consult.handoff_at is not None and consult.closed_at is None
    assert consult.customer_name == "홍길동"


def test_handoff_via_button_sets_customer_request(app, client, ai):
    client.post("/api/chat", json={"message": "질문"})
    client.post("/api/handoff", json={"name": "홍길동"})
    assert only_consult(app).handoff_reason == HandoffReason.customer_request


def test_handoff_without_any_message_creates_consult(app, client):
    assert client.post("/api/handoff", json={"name": "홍길동"}).status_code == 200
    consult = only_consult(app)
    assert consult.category is None and consult.message_count == 0


def test_handoff_twice_is_rejected(client, ai):
    client.post("/api/chat", json={"message": "질문"})
    client.post("/api/handoff", json={"name": "홍길동"})
    assert client.post("/api/handoff", json={"name": "홍길동"}).status_code == 409


def test_handoff_requires_name_and_session(client):
    assert client.post("/api/handoff", json={"name": "  "}).status_code == 400
    assert client.post("/api/end").status_code == 400      # 세션에 상담이 없으면 종료할 것도 없다
    assert client.post("/api/feedback", json={"satisfied": True}).status_code == 400


def test_client_cannot_pick_someone_elses_consult(app, client, ai):
    """consult_id 를 요청에 실어 보내도 무시하고 세션의 상담만 다룬다."""
    other = client.application.test_client()
    other.post("/api/chat", json={"message": "다른 사람의 질문"})
    client.post("/api/chat", json={"message": "내 질문"})
    client.post("/api/end", json={"consult_id": 1})
    with app.app_context():
        statuses = {c.consult_id: c.status for c in db.session.scalars(db.select(Consult))}
    assert statuses == {1: ConsultStatus.chatting, 2: ConsultStatus.ended}


def test_session_close_starts_fresh(app, client, ai):
    client.post("/api/chat", json={"message": "첫 상담"})
    client.post("/api/session/close")
    client.post("/api/chat", json={"message": "새 상담"})
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Consult.consult_id))) == 2
        assert db.session.scalar(db.select(db.func.count(db.distinct(Consult.customer_id)))) == 2


def test_new_chat_after_end_starts_new_consult(app, client, ai):
    client.post("/api/chat", json={"message": "첫 질문"})
    client.post("/api/end")
    client.post("/api/chat", json={"message": "또 질문"})
    with app.app_context():
        assert sorted(c.status.value for c in db.session.scalars(db.select(Consult))) == ["chatting", "ended"]
