"""상담 1건 (질문 스레드 단위). 고객 한 명이 방문 중 여러 건을 만들 수 있다."""
import enum

from app.extensions import db, utcnow


class ConsultStatus(enum.Enum):
    ai_resolved = "ai_resolved"              # AI 답변으로 종료됨
    waiting_realtime = "waiting_realtime"    # 영업시간 내, 실시간 상담사 대기
    waiting_next_day = "waiting_next_day"    # 영업시간 외, 익일 상담 예약 대기
    in_progress = "in_progress"              # 상담사가 상담 진행 중
    completed = "completed"                  # 상담사 상담까지 종료됨


class HandoffReason(enum.Enum):
    user_dissatisfied = "user_dissatisfied"      # 사용자가 AI 답변에 불만족 클릭
    ai_low_confidence = "ai_low_confidence"       # AI가 스스로 답변 불가로 판단


class Satisfaction(enum.Enum):
    satisfied = "satisfied"
    dissatisfied = "dissatisfied"


class QueueType(enum.Enum):
    """이관 결정 시점(영업시간 내/외)에 한 번만 기록하고 이후 절대 안 바꾼다.
    `status`는 진행되면서 계속 바뀌어서(waiting_realtime -> in_progress -> completed),
    "원래 실시간 건이었는지 예약 건이었는지"를 나중에도 통계 낼 수 있으려면 별도 필드가 필요하다."""
    realtime = "realtime"
    next_day = "next_day"


class Consult(db.Model):
    __tablename__ = "consult"

    consult_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.customer_id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.employee_id"), nullable=True)  # AI 단독 해결이면 NULL

    category = db.Column(db.String(20), nullable=True)      # 은행 / 보험 / 증권 (AI 판단)
    topic = db.Column(db.String(100), nullable=True)
    confidence = db.Column(db.Float, nullable=True)

    status = db.Column(db.Enum(ConsultStatus), nullable=False, default=ConsultStatus.ai_resolved)
    handoff_reason = db.Column(db.Enum(HandoffReason), nullable=True)
    queue_type = db.Column(db.Enum(QueueType), nullable=True)  # 상담사 이관이 결정된 시점의 영업시간 내/외 (통계용, 불변)
    satisfaction = db.Column(db.Enum(Satisfaction), nullable=True)
    summary = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    customer = db.relationship("Customer", back_populates="consults")
    employee = db.relationship("Employee", back_populates="consults")
    messages = db.relationship(
        "Message", back_populates="consult", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
