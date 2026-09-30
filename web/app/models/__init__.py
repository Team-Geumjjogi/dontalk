"""DB 모델 모음. 다른 곳에서는 `from app.models import Customer` 형태로 가져다 쓴다."""
from app.models.consult import Consult, ConsultStatus, HandoffReason, QueueType, Satisfaction
from app.models.customer import Customer
from app.models.employee import Employee, EmployeeRole
from app.models.message import Message, Sender

__all__ = [
    "Customer",
    "Employee", "EmployeeRole",
    "Consult", "ConsultStatus", "HandoffReason", "QueueType", "Satisfaction",
    "Message", "Sender",
]
