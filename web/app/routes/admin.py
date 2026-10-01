"""관리자 대시보드. 전부 실제 DB 집계 쿼리다 (가짜 숫자 없음).

지금은 테스트 데이터가 적어서 수치가 작게 나오는 게 정상이다 — 로직 자체는 실제 서비스에서도
그대로 쓸 수 있게 만들었고, 데모 때 그럴듯하게 보이려면 시드 스크립트로 테스트 데이터를 채우면 된다.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, render_template, request
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.authz import role_required
from app.extensions import db
from app.models import CATEGORIES, Consult, ConsultStatus, ConsultTransfer, Employee, EmployeeRole, QueueType, Satisfaction
from app.services.business_hours import KST
from app.services.classification_stats import classification_stats

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
        classification=classification_stats(),
    )


# ---------- 상담 이력 ----------
PAGE_SIZE = 20
STATUS_FILTERS = {  # 화면 필터 값 -> 실제 상태들
    "chatting": (ConsultStatus.chatting,),
    "ended": (ConsultStatus.ended,),
    "waiting": (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day),
    "completed": (ConsultStatus.completed,),
}
UNCLASSIFIED_FILTER = "unclassified"


def _kst_day_start(day: str | None) -> datetime | None:
    """'2026-10-01' 같은 날짜 문자열을 그날 0시(한국 시간)로. 형식이 잘못되면 None."""
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=KST) if day else None
    except ValueError:
        return None


@bp.route("/consults")
@role_required(EmployeeRole.admin)
def consults():
    """상담 이력: 분야/상태/상담사/기간으로 걸러서 본다. 완료한 상담의 채팅 기록은 상세에서 확인한다."""
    category = request.args.get("category", "all")
    status = request.args.get("status", "all")
    agent_id = request.args.get("agent", type=int)
    date_from, date_to = request.args.get("date_from", ""), request.args.get("date_to", "")

    query = (
        db.select(Consult)
        .options(joinedload(Consult.customer), joinedload(Consult.employee), selectinload(Consult.transfers), selectinload(Consult.messages))
        .order_by(Consult.created_at.desc(), Consult.consult_id.desc())
    )
    if category in CATEGORIES:
        query = query.where(Consult.category == category)
    elif category == UNCLASSIFIED_FILTER:
        query = query.where(Consult.category.is_(None))
    if status in STATUS_FILTERS:
        query = query.where(Consult.status.in_(STATUS_FILTERS[status]))
    if agent_id:
        query = query.where(Consult.employee_id == agent_id)
    if start := _kst_day_start(date_from):
        query = query.where(Consult.created_at >= start)
    if end := _kst_day_start(date_to):
        query = query.where(Consult.created_at < end + timedelta(days=1))  # 종료일 당일까지 포함

    filters = {"category": category, "status": status, "agent": agent_id, "date_from": date_from, "date_to": date_to}
    pagination = db.paginate(query, page=request.args.get("page", 1, type=int), per_page=PAGE_SIZE, error_out=False)
    agents = db.session.scalars(db.select(Employee).where(Employee.role == EmployeeRole.agent).order_by(Employee.name)).all()
    return render_template(
        "admin_consults.html",
        pagination=pagination,
        agent_options=[("", "전체")] + [(a.employee_id, f"{a.name} ({a.department})") for a in agents],
        filters=filters,
        params={key: value for key, value in filters.items() if value not in (None, "", "all")},  # 페이지 이동 링크에 유지할 조건
    )


@bp.route("/consults/<int:consult_id>")
@role_required(EmployeeRole.admin)
def consult_detail(consult_id):
    consult = db.session.get(
        Consult, consult_id,
        options=[joinedload(Consult.customer), joinedload(Consult.employee), selectinload(Consult.messages),
                 selectinload(Consult.transfers).joinedload(ConsultTransfer.employee)],
    )
    if consult is None:
        abort(404)
    return render_template("admin_consult_detail.html", consult=consult)
