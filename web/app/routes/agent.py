"""상담사 화면: 대기큐 + 상담 상세.

흐름 (플로우차트 "상담원"): 로그인 -> 대기큐 -> 상담 건 선택 -> 고객 문의 확인 -> 상담 진행/답변 -> 상담 완료
"임시저장"은 답변만 남기고 큐에 남겨두고(진행중), "상담완료 및 종료"는 답변을 남기고 상담을 끝낸다.
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user

from app.authz import role_required
from app.extensions import db
from app.models import Consult, ConsultStatus, EmployeeRole, Message, Sender

bp = Blueprint("agent", __name__, url_prefix="/agent")

WAITING_STATUSES = (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day)


@bp.route("/")
@role_required(EmployeeRole.agent)
def queue():
    category = request.args.get("category", "all")
    selected_id = request.args.get("consult_id", type=int)

    query = Consult.query.filter(Consult.status.in_(WAITING_STATUSES), Consult.employee_id.is_(None))
    if category == "reserved":
        query = query.filter(Consult.status == ConsultStatus.waiting_next_day)
    elif category in ("은행", "보험", "증권"):
        query = query.filter(Consult.category == category)
    waiting_consults = query.order_by(Consult.created_at).all()

    selected = None
    if selected_id:
        selected = db.session.get(Consult, selected_id)
        # 이미 다른 상담사가 가져갔거나 없는 건이면 선택 해제
        if selected and selected.employee_id not in (None, current_user.employee_id):
            selected = None

    return render_template(
        "agent_queue.html",
        waiting_consults=waiting_consults,
        selected=selected,
        category=category,
    )


@bp.route("/consult/<int:consult_id>/reply", methods=["POST"])
@role_required(EmployeeRole.agent)
def reply(consult_id):
    consult = db.session.get(Consult, consult_id)
    if consult is None:
        abort(404)
    if consult.employee_id not in (None, current_user.employee_id):
        abort(403)  # 이미 다른 상담사가 처리 중인 건

    content = (request.form.get("content") or "").strip()
    action = request.form.get("action")  # "save" 또는 "complete"

    consult.employee_id = current_user.employee_id  # 이 상담사가 담당(claim)
    if content:
        db.session.add(Message(consult_id=consult.consult_id, sender=Sender.agent, content=content))

    if action == "complete":
        consult.status = ConsultStatus.completed
    else:
        consult.status = ConsultStatus.in_progress

    db.session.commit()

    if action == "complete":
        return redirect(url_for("agent.queue"))
    return redirect(url_for("agent.queue", consult_id=consult.consult_id))
