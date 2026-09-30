"""고객. 로그인이 없어서 방문(세션)마다 하나씩 생긴다.

`name`은 처음엔 비어있다가, 챗봇 답변에 불만족하거나 AI가 답변 불가로 판단해서
상담사에게 이관하기로 결정되는 시점에만 입력받아 채워진다 (그 전까진 익명 채팅만 함).
"""
from app.extensions import db, utcnow


class Customer(db.Model):
    __tablename__ = "customer"

    customer_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    consults = db.relationship(
        "Consult", back_populates="customer", cascade="all, delete-orphan"
    )
