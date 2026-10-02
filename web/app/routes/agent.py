"""상담사 화면: 대기 큐(내 분야 + 미분류) / 내 완료 상담 + 상담 상세.

흐름: 로그인 -> 대기 큐 -> 상담 건 선택 -> 고객 문의/AI 분석/대화 내역 확인
        ├ 상담 메모 저장 -> 상담 종료 (완료한 건은 "내 완료" 탭에서 다시 볼 수 있다)
        └ 내 분야가 아니면 다른 분야로 이관 (consult_transfer 에 기록 -> 관리자 대시보드의 AI 분류 오류율)
상담사는 고객과 대화하지 않는다(고객에게 답변이 전달되지 않음). 마지막 단계는 상담 정리/메모(consult.summary) 저장이다.
분야 판단(AI)이 안 된 건(category 없음)은 "미분류"로 모든 상담사의 큐에 보이고, 누군가 종료하면 그 상담사의 분야로 배정된다.
"""
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app.authz import role_required
from app.extensions import db
from app.models import CATEGORIES, UNCLASSIFIED, Consult, ConsultStatus, ConsultTransfer, EmployeeRole

bp = Blueprint("agent", __name__, url_prefix="/agent")

WAITING_STATUSES = (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day)
DONE_LIST_LIMIT = 50  # "내 완료" 탭에 보여주는 최근 건수
_LOAD = (joinedload(Consult.customer), selectinload(Consult.messages), selectinload(Consult.transfers).joinedload(ConsultTransfer.employee))


def _waiting_filter():
    """내 분야로 분류된 대기 건 + 아직 분야가 없는(미분류) 건."""
    return db.and_(
        Consult.status.in_(WAITING_STATUSES),
        db.or_(Consult.category == current_user.department, Consult.category.is_(None)),
    )


def _waiting_consults() -> list[Consult]:
    # 건마다 고객/메시지를 따로 조회하지 않도록(N+1) 한 번에 같이 가져온다. DB가 원격이라 쿼리 수가 곧 응답 시간이다.
    return db.session.scalars(
        db.select(Consult).where(_waiting_filter()).options(*_LOAD).order_by(Consult.handoff_at, Consult.consult_id)
    ).all()


def _done_consults() -> list[Consult]:
    return db.session.scalars(
        db.select(Consult)
        .where(Consult.status == ConsultStatus.completed, Consult.employee_id == current_user.employee_id)
        .options(*_LOAD).order_by(Consult.closed_at.desc()).limit(DONE_LIST_LIMIT)
    ).all()


def _queue_items(consults: list[Consult]) -> list[dict]:
    return [{"consult": c, "preview": c.first_question} for c in consults]


@bp.route("/")
@role_required(EmployeeRole.agent)
def queue():
    tab = "done" if request.args.get("tab") == "done" else "waiting"
    consults = _done_consults() if tab == "done" else _waiting_consults()
    waiting_count = len(consults) if tab == "waiting" else db.session.scalar(db.select(db.func.count(Consult.consult_id)).where(_waiting_filter()))

    selected = None
    selected_id = request.args.get("consult_id", type=int)
    if selected_id:
        selected = next((c for c in consults if c.consult_id == selected_id), None)  # 현재 탭의 목록에 있는 건만 열 수 있다

    return render_template(
        "agent_queue.html",
        tab=tab,
        queue_items=_queue_items(consults),
        waiting_count=waiting_count,
        transfer_options=[(name, name) for name in CATEGORIES if selected and name != selected.category],  # 이관할 수 있는 분야
        selected=selected,
        selected_question=selected.first_question if selected else "",
    )


@bp.route("/queue/items")
@role_required(EmployeeRole.agent)
def queue_items():
    """대기 큐 목록만 다시 그린 조각. 화면이 주기적으로 불러가서 새 상담을 반영한다 (static/js/agent.js)."""
    consults = _waiting_consults()
    html = render_template(
        "partials/agent_queue_items.html",
        tab="waiting",
        queue_items=_queue_items(consults),
        selected=next((c for c in consults if c.consult_id == request.args.get("consult_id", type=int)), None),
    )
    return jsonify({"count": len(consults), "html": html})


def _handleable(consult: Consult | None) -> bool:
    """내가 처리/이관할 수 있는 건인가: 대기 중이고, 내 분야이거나 미분류."""
    return consult is not None and consult.status in WAITING_STATUSES and consult.category in (current_user.department, None)


@bp.route("/consult/<int:consult_id>/complete", methods=["POST"])
@role_required(EmployeeRole.agent)
def complete(consult_id):
    consult = db.session.get(Consult, consult_id)
    if consult is None:
        abort(404)
    if consult.status not in WAITING_STATUSES:
        flash("이미 처리된 상담입니다.", "info")
        return redirect(url_for("agent.queue"))
    if not _handleable(consult):
        abort(403)  # 다른 분야 상담사의 건

    summary = (request.form.get("summary") or "").strip()
    if not summary:
        flash("상담 메모를 입력해 주세요.", "danger")
        return redirect(url_for("agent.queue", consult_id=consult_id))

    if consult.category is None:  # 미분류 건은 처리한 상담사의 분야로 배정된다 (ai_category 는 비어 있어 오분류로 세지 않는다)
        consult.category = current_user.department
    consult.summary = summary
    consult.employee_id = current_user.employee_id
    consult.status = ConsultStatus.completed
    consult.closed_at = datetime.now(timezone.utc)
    db.session.commit()

    flash("상담을 종료했습니다.", "success")
    return redirect(url_for("agent.queue"))


@bp.route("/consult/<int:consult_id>/transfer", methods=["POST"])
@role_required(EmployeeRole.agent)
def transfer(consult_id):
    """상담사가 보기에 다른 분야 문의일 때 해당 분야 큐로 넘긴다. 기록은 consult_transfer 에 남는다."""
    consult = db.session.get(Consult, consult_id)
    if not _handleable(consult):
        flash("이미 처리되었거나 이관할 수 없는 상담입니다.", "info")
        return redirect(url_for("agent.queue"))

    to_category = request.form.get("to_category")
    reason = (request.form.get("reason") or "").strip() or None
    if to_category not in CATEGORIES or to_category == consult.category:
        flash("이관할 분야를 선택해 주세요.", "danger")
        return redirect(url_for("agent.queue", consult_id=consult_id))

    db.session.add(ConsultTransfer(
        consult_id=consult.consult_id, employee_id=current_user.employee_id,
        from_category=consult.category or UNCLASSIFIED, to_category=to_category, reason=reason,
    ))
    consult.category = to_category
    db.session.commit()

    if to_category == current_user.department:  # 미분류 건을 내 분야로 가져온 경우
        flash(f"{to_category} 분야로 배정했습니다.", "success")
        return redirect(url_for("agent.queue", consult_id=consult_id))
    flash(f"{to_category} 담당 상담사에게 이관했습니다.", "success")
    return redirect(url_for("agent.queue"))
