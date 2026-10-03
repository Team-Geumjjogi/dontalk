"""상담 1건 (질문 스레드 단위). 고객 한 명이 방문 중 여러 건을 만들 수 있다.

흐름: chatting(AI 상담 중) ─ 고객이 종료 ─▶ ended
                          └ 상담사 연결 ─▶ waiting_realtime / waiting_next_day ─ 상담사가 메모 저장 ─▶ completed
"""
import enum

from app.extensions import db, utcnow

CATEGORIES = ("은행", "보험", "증권")  # 분야 값. consult.category / ai_category / employee.department / consult_transfer 가 모두 같은 값을 쓴다.
UNCLASSIFIED = "미분류"                 # AI가 분야를 못 정한 상담. DB에는 category=NULL 로 저장하고, consult_transfer.from_category 에만 이 문자열을 쓴다.


class ConsultStatus(enum.Enum):
    chatting = "chatting"                    # AI와 상담 중 (새 상담의 기본값)
    ended = "ended"                          # 고객이 상담을 종료함 (상담사 연결 없이 AI 상담만으로 끝)
    waiting_realtime = "waiting_realtime"    # 영업시간 내, 실시간 상담사 대기
    waiting_next_day = "waiting_next_day"    # 영업시간 외, 익일 상담 예약 대기
    completed = "completed"                  # 상담사가 상담 메모를 저장하고 완전히 종료함

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


class HandoffReason(enum.Enum):
    customer_request = "customer_request"    # 고객이 상담사 연결을 직접 요청 (버튼 또는 "상담사 연결해 주세요")
    action_request = "action_request"        # 계좌 해지·이체 같은 실제 처리 요청 (AI는 안내만 가능)
    no_basis = "no_basis"                    # 관련 상담 근거를 못 찾음 (업무 밖/정보 부족)
    low_confidence = "low_confidence"        # 분야 판단 확신도가 낮음
    ai_error = "ai_error"                    # AI 서버/검색/LLM 오류
    user_dissatisfied = "user_dissatisfied"  # 상담 종료 후 불만족이라고 답하고 상담사 연결을 선택

    @property
    def label(self) -> str:
        return _HANDOFF_LABELS[self]


class Satisfaction(enum.Enum):
    satisfied = "satisfied"
    dissatisfied = "dissatisfied"

    @property
    def label(self) -> str:
        return "만족" if self is Satisfaction.satisfied else "불만족"


class QueueType(enum.Enum):
    """이관 결정 시점(영업시간 내/외)에 한 번만 기록하고 이후 절대 안 바꾼다.
    `status`는 진행되면서 계속 바뀌어서(waiting_realtime -> completed),
    "원래 실시간 건이었는지 예약 건이었는지"를 나중에도 통계 낼 수 있으려면 별도 필드가 필요하다."""
    realtime = "realtime"
    next_day = "next_day"


# 화면에 보여줄 한글 이름 (템플릿에서 status.label / handoff_reason.label 로 쓴다)
_STATUS_LABELS = {
    ConsultStatus.chatting: "상담 중",
    ConsultStatus.ended: "AI 상담 종료",
    ConsultStatus.waiting_realtime: "대기중",
    ConsultStatus.waiting_next_day: "예약",
    ConsultStatus.completed: "완료",
}
_HANDOFF_LABELS = {
    HandoffReason.customer_request: "고객이 상담사 연결을 요청",
    HandoffReason.action_request: "처리 요청 (해지·이체 등)",
    HandoffReason.no_basis: "답변 근거를 찾지 못함",
    HandoffReason.low_confidence: "분야 판단이 불확실",
    HandoffReason.ai_error: "AI 오류",
    HandoffReason.user_dissatisfied: "상담 종료 후 불만족",
}


class Consult(db.Model):
    __tablename__ = "consult"

    consult_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.customer_id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.employee_id"), nullable=True)  # 상담을 완료한 상담사. AI 단독 종료면 NULL

    category = db.Column(db.String(20), nullable=True)      # 현재 배정된 분야(은행/보험/증권). 상담사가 다른 분야로 재배정하면 바뀐다
    ai_category = db.Column(db.String(20), nullable=True)   # 이관 시점에 AI가 판단한 분야. 이후 안 바뀜 → 분류 오류율 계산용
    topic = db.Column(db.String(100), nullable=True)
    confidence = db.Column(db.Float, nullable=True)

    status = db.Column(db.Enum(ConsultStatus), nullable=False, default=ConsultStatus.chatting)
    handoff_reason = db.Column(db.Enum(HandoffReason), nullable=True)
    handoff_detail = db.Column(db.Text, nullable=True)      # AI가 알려준 상세 사유 (예: "최고 유사도 0.50 < 0.55")
    queue_type = db.Column(db.Enum(QueueType), nullable=True)  # 이관이 결정된 시점의 영업시간 내/외 (통계용, 불변)
    satisfaction = db.Column(db.Enum(Satisfaction), nullable=True)
    summary = db.Column(db.Text, nullable=True)             # 상담사가 남기는 상담 정리/메모 (1회, 저장하면 상담 종료)

    handoff_at = db.Column(db.DateTime(timezone=True), nullable=True)  # 상담사 연결을 접수한 시각 (대기 시간 계산용)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)   # 고객이 종료했거나 상담사가 완료한 시각
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    @property
    def first_question(self) -> str:
        """고객이 처음 보낸 질문 (목록 미리보기, 상세의 "원본 문의")."""
        return next((m.content for m in self.messages if m.sender.value == "customer"), "")

    customer = db.relationship("Customer", back_populates="consults")
    employee = db.relationship("Employee", back_populates="consults")
    messages = db.relationship(
        "Message", back_populates="consult", cascade="all, delete-orphan",
        order_by="Message.message_id",
    )
    transfers = db.relationship(
        "ConsultTransfer", back_populates="consult", cascade="all, delete-orphan",
        order_by="ConsultTransfer.transfer_id",
    )
