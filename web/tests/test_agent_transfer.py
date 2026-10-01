"""상담사: 분야 이관, 미분류 처리, 완료 상담 열람, 큐 자동 갱신 조각."""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Consult, ConsultStatus, ConsultTransfer
from helpers import add_consult, agent_id


def transfers(app):
    with app.app_context():
        return [(t.from_category, t.to_category, t.reason) for t in db.session.scalars(db.select(ConsultTransfer))]


def consult_state(app, consult_id):
    with app.app_context():
        c = db.session.get(Consult, consult_id)
        return c.category, c.ai_category, c.status


# ---------- 분야 이관 ----------
def test_transfer_moves_consult_to_other_departments_queue(app, login):
    consult_id = add_consult(app, "은행", question="보험금 청구 문의", ai_category="은행")
    response = login("bank@test.com").post(f"/agent/consult/{consult_id}/transfer", data={"to_category": "보험", "reason": "보험 문의임"})
    assert response.status_code == 302
    assert consult_state(app, consult_id) == ("보험", "은행", ConsultStatus.waiting_realtime)   # 현재 분야만 바뀌고 AI 판단은 그대로
    assert transfers(app) == [("은행", "보험", "보험 문의임")]
    assert "보험금 청구 문의" not in login("bank@test.com").get("/agent/").get_data(as_text=True)
    assert "보험금 청구 문의" in login("ins@test.com").get("/agent/").get_data(as_text=True)


def test_transfer_rejects_invalid_or_same_category(app, login):
    consult_id = add_consult(app, "은행")
    client = login("bank@test.com")
    client.post(f"/agent/consult/{consult_id}/transfer", data={"to_category": "은행"})       # 같은 분야
    client.post(f"/agent/consult/{consult_id}/transfer", data={"to_category": "부동산"})     # 없는 분야
    client.post(f"/agent/consult/{consult_id}/transfer", data={})
    assert transfers(app) == [] and consult_state(app, consult_id)[0] == "은행"


def test_cannot_transfer_other_departments_consult(app, login):
    consult_id = add_consult(app, "보험")
    login("bank@test.com").post(f"/agent/consult/{consult_id}/transfer", data={"to_category": "증권"})
    assert transfers(app) == [] and consult_state(app, consult_id)[0] == "보험"


def test_unclassified_can_be_assigned_and_is_logged_as_unclassified(app, login):
    consult_id = add_consult(app, None)
    login("bank@test.com").post(f"/agent/consult/{consult_id}/transfer", data={"to_category": "증권"})
    assert transfers(app) == [("미분류", "증권", None)] and consult_state(app, consult_id)[0] == "증권"


def test_completing_unclassified_assigns_agents_department(app, login):
    consult_id = add_consult(app, None)
    login("ins@test.com").post(f"/agent/consult/{consult_id}/complete", data={"summary": "보험 문의 처리"})
    assert consult_state(app, consult_id) == ("보험", None, ConsultStatus.completed)  # ai_category 는 비어 있어 오분류로 세지 않는다


# ---------- 완료 상담 열람 ----------
def test_done_tab_lists_only_my_completed_consults_read_only(app, login):
    mine = add_consult(app, "은행", status=ConsultStatus.completed, question="내가 끝낸 문의", employee_id=agent_id(app, "bank@test.com"),
                       summary="안내 완료", closed_at=datetime.now(timezone.utc))
    add_consult(app, "은행", status=ConsultStatus.completed, question="남이 끝낸 문의", employee_id=agent_id(app, "ins@test.com"))
    add_consult(app, "은행", question="아직 대기 중")
    client = login("bank@test.com")
    html = client.get("/agent/?tab=done").get_data(as_text=True)
    assert "내가 끝낸 문의" in html and "남이 끝낸 문의" not in html and "아직 대기 중" not in html
    detail = client.get(f"/agent/?tab=done&consult_id={mine}").get_data(as_text=True)
    assert "안내 완료" in detail and 'name="summary"' not in detail and "분야 이관하기" not in detail   # 읽기 전용


def test_done_detail_of_someone_elses_consult_is_not_shown(app, login):
    other = add_consult(app, "은행", status=ConsultStatus.completed, question="남의 문의", employee_id=agent_id(app, "ins@test.com"))
    assert "남의 문의" not in login("bank@test.com").get(f"/agent/?tab=done&consult_id={other}").get_data(as_text=True)


# ---------- 큐 자동 갱신 ----------
def test_queue_items_fragment_returns_count_and_html(app, login):
    add_consult(app, "은행", question="새 문의 하나")
    add_consult(app, "보험")
    data = login("bank@test.com").get("/agent/queue/items").get_json()
    assert data["count"] == 1 and "새 문의 하나" in data["html"]


def test_queue_items_requires_agent(client, login):
    assert client.get("/agent/queue/items").status_code == 302
    assert login("admin@test.com").get("/agent/queue/items").status_code == 403
