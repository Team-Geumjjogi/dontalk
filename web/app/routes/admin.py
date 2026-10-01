"""관리자 대시보드. 전부 실제 DB 집계 쿼리다 (가짜 숫자 없음).

지금은 테스트 데이터가 적어서 수치가 작게 나오는 게 정상이다 — 로직 자체는 실제 서비스에서도
그대로 쓸 수 있게 만들었고, 데모 때 그럴듯하게 보이려면 시드 스크립트로 테스트 데이터를 채우면 된다.
"""
from datetime import datetime, timezone

from flask import Blueprint, render_template
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.authz import role_required
from app.extensions import db
from app.models import Consult, ConsultStatus, Employee, EmployeeRole, QueueType, Satisfaction
from app.services.business_hours import KST

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _as_utc(moment: datetime) -> datetime:
    """DB에서 timezone 정보 없이 나온 시각(sqlite 등)은 UTC 로 간주한다."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@bp.route("/")
@role_required(EmployeeRole.admin)
def dashboard():
    now_kst = datetime.now(KST)
    today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    today_consults = Consult.query.filter(Consult.created_at >= today_start)
    total_today = today_consults.count()
    # AI 단독 해결 = 상담사 연결 없이 고객이 종료했고(ended), 불만족이 아닌 건
    ai_only_today = today_consults.filter(
        Consult.status == ConsultStatus.ended,
        db.or_(Consult.satisfaction.is_(None), Consult.satisfaction == Satisfaction.satisfied),
    ).count()
    ai_only_rate = round(ai_only_today / total_today * 100, 1) if total_today else 0.0

    handed_off = Consult.query.filter(Consult.handoff_at.isnot(None)).count()
    realtime_count = Consult.query.filter(Consult.queue_type == QueueType.realtime).count()
    reserved_count = Consult.query.filter(Consult.queue_type == QueueType.next_day).count()
    handoff_rate = round(handed_off / total_today * 100, 1) if total_today else 0.0

    feedback_total = Consult.query.filter(Consult.satisfaction.isnot(None)).count()
    satisfied_total = Consult.query.filter(Consult.satisfaction == Satisfaction.satisfied).count()
    satisfaction_rate = round(satisfied_total / feedback_total * 100, 1) if feedback_total else None

    waiting_statuses = (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day)
    waiting_now = Consult.query.filter(Consult.status.in_(waiting_statuses)).count()
    agent_count = Employee.query.filter(Employee.role == EmployeeRole.agent).count()

    # 대기 중인 건들의 평균 대기 시간 (분) — 상담사 연결을 접수한 시각부터 지금까지
    waiting_since = [c.handoff_at for c in Consult.query.filter(Consult.status.in_(waiting_statuses)).all() if c.handoff_at]
    now_utc = datetime.now(timezone.utc)
    avg_wait_minutes = round(sum((now_utc - _as_utc(t)).total_seconds() for t in waiting_since) / len(waiting_since) / 60, 1) if waiting_since else 0.0

    category_counts = (
        db.session.query(Consult.category, func.count(Consult.consult_id))
        .group_by(Consult.category)
        .all()
    )
    category_counts = [(cat or "분류중", n) for cat, n in category_counts]
    category_total = sum(n for _, n in category_counts) or 1

    recent_logs = Consult.query.options(joinedload(Consult.customer)).order_by(Consult.updated_at.desc()).limit(10).all()

    return render_template(
        "admin_dashboard.html",
        total_today=total_today,
        ai_only_today=ai_only_today,
        ai_only_rate=ai_only_rate,
        handed_off=handed_off,
        realtime_count=realtime_count,
        reserved_count=reserved_count,
        handoff_rate=handoff_rate,
        feedback_total=feedback_total,
        satisfaction_rate=satisfaction_rate,
        waiting_now=waiting_now,
        agent_count=agent_count,
        avg_wait_minutes=avg_wait_minutes,
        category_counts=category_counts,
        category_total=category_total,
        recent_logs=recent_logs,
    )
