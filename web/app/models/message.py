"""상담 대화 메시지 (턴 단위). 채팅 히스토리를 그대로 재구성할 수 있게 각 발화를 한 행씩 저장한다.

상담사는 고객과 대화하지 않는다(메모만 남김). 그래서 발화자는 고객과 AI 둘뿐이다.
"""
import enum

from app.extensions import db, utcnow


class Sender(enum.Enum):
    customer = "customer"
    ai = "ai"


class Message(db.Model):
    __tablename__ = "message"

    message_id = db.Column(db.Integer, primary_key=True)
    consult_id = db.Column(db.Integer, db.ForeignKey("consult.consult_id"), nullable=False)
    sender = db.Column(db.Enum(Sender), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON(none_as_null=True), nullable=True)  # AI 답변일 때만: 근거로 쓴 상담 사례 목록 (상담사 화면의 예상 꼬리질문/답변용)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    consult = db.relationship("Consult", back_populates="messages")
