"""테스트 데이터 만들기 도우미 (테스트 파일들이 같이 쓴다)."""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Consult, ConsultStatus, Customer, Employee, Message, Sender


def add_consult(app, category, status=ConsultStatus.waiting_realtime, question="질문", **fields):
    with app.app_context():
        customer = Customer(name=f"{category or '미분류'}고객")
        db.session.add(customer)
        db.session.flush()
        consult = Consult(customer_id=customer.customer_id, category=category, status=status,
                          handoff_at=datetime.now(timezone.utc), **fields)
        db.session.add(consult)
        db.session.flush()
        db.session.add_all([Message(consult_id=consult.consult_id, sender=Sender.customer, content=question),
                            Message(consult_id=consult.consult_id, sender=Sender.ai, content="답변",
                                    sources=[{"snippet": "사례", "topic": "t", "score": 0.7, "follow_up_question": "꼬리질문?", "output": "종합"}])])
        db.session.commit()
        return consult.consult_id



def agent_id(app, email):
    """이메일로 상담사/관리자의 employee_id 를 찾는다."""
    with app.app_context():
        return db.session.scalar(db.select(Employee.employee_id).where(Employee.email == email))
