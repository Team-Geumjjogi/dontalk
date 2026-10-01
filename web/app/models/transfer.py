"""분야 재배정 기록. 상담사가 "우리 분야가 아니다"라고 판단해 다른 분야 상담사에게 넘길 때 한 줄씩 남는다.

AI 분류 오류율 = (재배정된 상담 수) / (이관된 상담 수) 로 계산한다 (관리자 대시보드).
"""
from app.extensions import db, utcnow


class ConsultTransfer(db.Model):
    __tablename__ = "consult_transfer"

    transfer_id = db.Column(db.Integer, primary_key=True)
    consult_id = db.Column(db.Integer, db.ForeignKey("consult.consult_id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.employee_id"), nullable=False)  # 재배정한 상담사
    from_category = db.Column(db.String(20), nullable=False)
    to_category = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    consult = db.relationship("Consult", back_populates="transfers")
    employee = db.relationship("Employee")
