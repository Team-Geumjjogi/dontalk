"""상담 대화 메시지 (턴 단위). 채팅 히스토리를 그대로 재구성할 수 있게 각 발화를 한 행씩 저장한다."""
import enum

from app.extensions import db, utcnow


class Sender(enum.Enum):
    customer = "customer"
    ai = "ai"
    agent = "agent"


class Message(db.Model):
    __tablename__ = "message"

    message_id = db.Column(db.Integer, primary_key=True)
    consult_id = db.Column(db.Integer, db.ForeignKey("consult.consult_id"), nullable=False)
    sender = db.Column(db.Enum(Sender), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    consult = db.relationship("Consult", back_populates="messages")
