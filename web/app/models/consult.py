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
