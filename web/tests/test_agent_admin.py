"""상담사(분야별 큐, 상담 메모로 종료)와 관리자 대시보드."""
from sqlalchemy import event

from app.extensions import db
from app.models import Consult, ConsultStatus, Satisfaction
from helpers import add_consult


def test_agent_sees_only_own_department_and_unclassified(app, login):
    add_consult(app, "은행", question="은행 문의")
    add_consult(app, "보험", question="보험 문의")
    add_consult(app, None, question="미분류 문의")
    add_consult(app, "은행", status=ConsultStatus.chatting, question="아직 상담 중")  # 대기가 아닌 건은 안 보인다
    html = login("bank@test.com").get("/agent/").get_data(as_text=True)
    assert "은행 문의" in html and "미분류 문의" in html
    assert "보험 문의" not in html and "아직 상담 중" not in html
    assert "은행 상담" in html and "대기 2건" in html


def test_agent_detail_shows_analysis_and_sources(app, login):
    consult_id = add_consult(app, "은행", question="원본 문의", topic="대출", confidence=0.8)
    html = login("bank@test.com").get(f"/agent/?consult_id={consult_id}").get_data(as_text=True)
    assert "원본 문의" in html and "80%" in html
    assert "예상 꼬리질문" in html and "꼬리질문?" in html          # 근거 사례의 꼬리질문/답변
    assert 'name="summary"' in html and "저장하고 상담 종료" in html


def test_agent_cannot_open_other_department_consult(app, login):
    consult_id = add_consult(app, "보험", question="보험 문의")
    assert "보험 문의" not in login("bank@test.com").get(f"/agent/?consult_id={consult_id}").get_data(as_text=True)


def test_complete_saves_memo_and_closes(app, login):
    consult_id = add_consult(app, "은행")
    response = login("bank@test.com").post(f"/agent/consult/{consult_id}/complete", data={"summary": "대출 연장 안내 완료"})
    assert response.status_code == 302
    with app.app_context():
        consult = db.session.get(Consult, consult_id)
        assert consult.status == ConsultStatus.completed and consult.summary == "대출 연장 안내 완료"
        assert consult.employee.email == "bank@test.com" and consult.closed_at is not None


def test_complete_requires_memo(app, login):
    consult_id = add_consult(app, "은행")
    login("bank@test.com").post(f"/agent/consult/{consult_id}/complete", data={"summary": "   "})
    with app.app_context():
        assert db.session.get(Consult, consult_id).status == ConsultStatus.waiting_realtime


def test_complete_other_department_forbidden(app, login):
    consult_id = add_consult(app, "보험")
    assert login("bank@test.com").post(f"/agent/consult/{consult_id}/complete", data={"summary": "x"}).status_code == 403


def test_complete_already_done_is_not_overwritten(app, login):
    consult_id = add_consult(app, "은행", status=ConsultStatus.completed, summary="먼저 처리됨")
    login("bank@test.com").post(f"/agent/consult/{consult_id}/complete", data={"summary": "덮어쓰기"})
    with app.app_context():
        assert db.session.get(Consult, consult_id).summary == "먼저 처리됨"


def test_queue_query_count_does_not_grow_with_items(app, login):
    """대기 건마다 쿼리가 늘어나면(N+1) 원격 DB에서 느려진다. 3건과 20건의 쿼리 수가 같아야 한다."""
    client = login("bank@test.com")

    def count_queries():
        statements = []
        with app.app_context():
            listener = lambda *args: statements.append(1)
            event.listen(db.engine, "before_cursor_execute", listener)
            client.get("/agent/")
            event.remove(db.engine, "before_cursor_execute", listener)
        return len(statements)

    for _ in range(3):
        add_consult(app, "은행")
    few = count_queries()
    for _ in range(17):
        add_consult(app, "은행")
    assert count_queries() == few


def test_roles_are_separated(login):
    assert login("bank@test.com").get("/admin/").status_code == 403
    assert login("admin@test.com").get("/agent/").status_code == 403


def test_admin_dashboard_counts(app, login):
    add_consult(app, "은행", status=ConsultStatus.ended, satisfaction=Satisfaction.satisfied)
    add_consult(app, "은행", status=ConsultStatus.ended)                                        # 무응답 종료도 AI 해결
    add_consult(app, "보험", status=ConsultStatus.ended, satisfaction=Satisfaction.dissatisfied)  # 불만족은 제외
    add_consult(app, "증권")                                                                   # 이관 대기
    html = login("admin@test.com").get("/admin/").get_data(as_text=True)
    assert "AI 단독 해결 2건" in html and "현재 대기 중인 상담" in html
    assert "상담 분야별 비중" in html and "최근 상담 로그" in html


def count_queries(app, call):
    """call() 을 실행하는 동안 DB 로 나간 SQL 문장 수."""
    statements = []
    with app.app_context():
        listener = lambda *args: statements.append(1)
        event.listen(db.engine, "before_cursor_execute", listener)
        call()
        event.remove(db.engine, "before_cursor_execute", listener)
    return len(statements)


def test_dashboard_query_count_stays_small_regardless_of_data(app, login):
    """대시보드는 데이터가 늘어도 쿼리 수가 같고(원격 DB 지연 방지), 고정 상한 안이어야 한다."""
    admin = login("admin@test.com")
    for _ in range(3):
        add_consult(app, "은행", ai_category="은행")
    few = count_queries(app, lambda: admin.get("/admin/"))
    for _ in range(25):
        add_consult(app, "보험", status=ConsultStatus.ended, ai_category="보험")
    assert count_queries(app, lambda: admin.get("/admin/")) == few <= 6
