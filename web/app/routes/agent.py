"""상담사 화면: 내 분야(department)로 분류된 대기 건 + 상담 상세.

흐름: 로그인 -> 내 분야 대기큐 -> 상담 건 선택 -> 고객 문의/AI 분석/대화 내역 확인 -> 상담 메모 입력 -> 저장하면 상담 종료
상담사는 고객과 대화하지 않는다(고객에게 답변이 전달되지 않음). 마지막 단계는 상담 정리/메모(consult.summary) 저장이다.
분야 판단(AI)이 안 된 건(category 없음)은 "미분류"로 모든 상담사의 큐에 보인다.
"""
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app.authz import role_required
from app.extensions import db
from app.models import Consult, ConsultStatus, EmployeeRole, Sender

bp = Blueprint("agent", __name__, url_prefix="/agent")

WAITING_STATUSES = (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day)


def _queue_filter():
    """내 분야로 분류된 대기 건 + 아직 분야가 없는 건."""
    return db.and_(
        Consult.status.in_(WAITING_STATUSES),
        db.or_(Consult.category == current_user.department, Consult.category.is_(None)),
    )


def _first_question(consult: Consult) -> str:
    return next((m.content for m in consult.messages if m.sender == Sender.customer), "")


@bp.route("/")
@role_required(EmployeeRole.agent)
def queue():
    # 대기 건마다 고객/메시지를 따로 조회하지 않도록(N+1) 한 번에 같이 가져온다. DB가 원격이라 쿼리 수가 곧 응답 시간이다.
    waiting = db.session.scalars(
        db.select(Consult)
        .where(_queue_filter())
        .options(joinedload(Consult.customer), selectinload(Consult.messages))
        .order_by(Consult.handoff_at, Consult.consult_id)
    ).all()

    selected = None
    selected_id = request.args.get("consult_id", type=int)
    if selected_id:
        selected = next((c for c in waiting if c.consult_id == selected_id), None)  # 큐에 있는 건만 열 수 있다

    return render_template(
        "agent_queue.html",
        queue_items=[{"consult": c, "preview": _first_question(c)} for c in waiting],
        selected=selected,
        selected_question=_first_question(selected) if selected else "",
    )


@bp.route("/consult/<int:consult_id>/complete", methods=["POST"])
@role_required(EmployeeRole.agent)
def complete(consult_id):
    consult = db.session.get(Consult, consult_id)
    if consult is None:
        abort(404)
    if consult.status not in WAITING_STATUSES:
        flash("이미 처리된 상담입니다.", "info")
        return redirect(url_for("agent.queue"))
    if consult.category not in (current_user.department, None):
        abort(403)  # 다른 분야 상담사의 건

    summary = (request.form.get("summary") or "").strip()
    if not summary:
        flash("상담 메모를 입력해 주세요.", "danger")
        return redirect(url_for("agent.queue", consult_id=consult_id))

    consult.summary = summary
    consult.employee_id = current_user.employee_id
    consult.status = ConsultStatus.completed
    consult.closed_at = datetime.now(timezone.utc)
    db.session.commit()

    flash("상담을 종료했습니다.", "success")
    return redirect(url_for("agent.queue"))
