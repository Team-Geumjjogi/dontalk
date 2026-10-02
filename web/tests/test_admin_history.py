"""관리자: 상담 이력(필터/페이지네이션/상세)과 AI 분류 정확도."""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Consult, ConsultStatus, ConsultTransfer
from app.services.classification_stats import classification_stats
from helpers import add_consult, agent_id


# ---------- 관리자 상담 이력 ----------
def test_admin_history_filters(app, login):
    add_consult(app, "은행", status=ConsultStatus.ended, question="은행 종료 건")
    add_consult(app, "보험", question="보험 대기 건")
    add_consult(app, None, question="미분류 대기 건")
    add_consult(app, "증권", status=ConsultStatus.completed, question="증권 완료 건", employee_id=agent_id(app, "bank@test.com"))
    admin = login("admin@test.com")

    def page(**params):
        return admin.get("/admin/consults", query_string=params).get_data(as_text=True)

    assert all(t in page() for t in ("은행 종료 건", "보험 대기 건", "미분류 대기 건", "증권 완료 건"))
    only_ins = page(category="보험")
    assert "보험 대기 건" in only_ins and "은행 종료 건" not in only_ins
    assert "미분류 대기 건" in page(category="unclassified") and "보험 대기 건" not in page(category="unclassified")
    assert "증권 완료 건" in page(status="completed") and "은행 종료 건" not in page(status="completed")
    assert "보험 대기 건" in page(status="waiting") and "증권 완료 건" not in page(status="waiting")
    by_agent = page(agent=agent_id(app, "bank@test.com"))
    assert "증권 완료 건" in by_agent and "보험 대기 건" not in by_agent


def test_admin_history_date_filter_is_inclusive_and_pagination(app, login):
    old = add_consult(app, "은행", question="옛날 상담")
    with app.app_context():
        db.session.get(Consult, old).created_at = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        db.session.commit()
    add_consult(app, "은행", question="오늘 상담")
    admin = login("admin@test.com")
    jan = admin.get("/admin/consults", query_string={"date_from": "2026-01-15", "date_to": "2026-01-15"}).get_data(as_text=True)
    assert "옛날 상담" in jan and "오늘 상담" not in jan
    assert "필터를 바꾸거나" in admin.get("/admin/consults", query_string={"date_from": "2026-02-01", "date_to": "2026-02-02"}).get_data(as_text=True)
    assert admin.get("/admin/consults", query_string={"date_from": "잘못된값"}).status_code == 200   # 형식이 틀리면 무시

    for _ in range(24):
        add_consult(app, "보험")
    second = admin.get("/admin/consults", query_string={"category": "보험", "page": 2}).get_data(as_text=True)
    assert "2 / 2 페이지" in second and "category=%EB%B3%B4%ED%97%98" in second   # 페이지를 넘겨도 필터 유지


def test_admin_detail_shows_chat_memo_and_transfer_history(app, login):
    consult_id = add_consult(app, "보험", status=ConsultStatus.completed, question="상세 확인용 질문", summary="상담사 메모 내용",
                             employee_id=agent_id(app, "ins@test.com"), ai_category="은행", closed_at=datetime.now(timezone.utc))
    with app.app_context():
        db.session.add(ConsultTransfer(consult_id=consult_id, employee_id=agent_id(app, "bank@test.com"), from_category="은행", to_category="보험", reason="보험 문의"))
        db.session.commit()
    html = login("admin@test.com").get(f"/admin/consults/{consult_id}").get_data(as_text=True)
    assert all(t in html for t in ("상세 확인용 질문", "상담사 메모 내용", "은행 → 보험", "보험 문의", "박지훈"))
    assert login("admin@test.com").get("/admin/consults/9999").status_code == 404


def test_admin_history_is_admin_only(client, login):
    assert client.get("/admin/consults").status_code == 302
    assert login("bank@test.com").get("/admin/consults").status_code == 403
    assert login("bank@test.com").get("/admin/consults/1").status_code == 403


# ---------- AI 분류 정확도 ----------
def test_classification_stats(app):
    a = add_consult(app, "보험", ai_category="은행")              # 은행→보험 재배정 = 오분류
    add_consult(app, "은행", ai_category="은행")                  # 정상
    add_consult(app, "증권", ai_category="증권")                  # 정상
    add_consult(app, "은행", ai_category=None)                    # AI 미분류 (오류율에서 제외)
    add_consult(app, "은행", ai_category="은행", status=ConsultStatus.chatting, handoff_at=None) if False else None
    with app.app_context():
        db.session.add(ConsultTransfer(consult_id=a, employee_id=1, from_category="은행", to_category="보험"))
        db.session.add(ConsultTransfer(consult_id=a, employee_id=1, from_category="보험", to_category="증권"))   # 다시 이관해도 1건으로 센다
        db.session.commit()
        stats = classification_stats()
    rows = {r["category"]: r for r in stats["rows"]}
    assert (rows["은행"]["handed_off"], rows["은행"]["reassigned"], rows["은행"]["error_rate"]) == (2, 1, 50.0)
    assert (rows["보험"]["handed_off"], rows["증권"]["error_rate"]) == (0, 0.0)
    assert (rows["보험"]["error_rate"]) is None
    assert stats["total"]["handed_off"] == 3 and stats["total"]["reassigned"] == 1 and stats["unclassified"] == 1


def test_dashboard_shows_classification_accuracy(app, login):
    a = add_consult(app, "보험", ai_category="은행")
    add_consult(app, "은행", ai_category="은행")
    with app.app_context():
        db.session.add(ConsultTransfer(consult_id=a, employee_id=1, from_category="은행", to_category="보험"))
        db.session.commit()
    html = login("admin@test.com").get("/admin/").get_data(as_text=True)
    assert "AI 분류 정확도" in html and "분류 오류율" in html and "50.0%" in html
