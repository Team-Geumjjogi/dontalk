"""상담사 / 관리자 계정. 이 둘만 실제 로그인(이메일+비밀번호)을 한다."""
import enum

from flask_login import UserMixin

from app.extensions import db, utcnow


class EmployeeRole(enum.Enum):
    agent = "agent"   # 상담사
    admin = "admin"   # 관리자


class Employee(UserMixin, db.Model):
    """UserMixin: Flask-Login이 요구하는 is_authenticated/is_active/get_id() 등을 기본 구현으로 채워준다.
    (Spring Security의 UserDetails 인터페이스를 구현하는 것과 같은 역할)
    """

    __tablename__ = "employee"

    employee_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(EmployeeRole), nullable=False)
    department = db.Column(db.String(20), nullable=True)  # 은행/보험/증권 담당 (관리자는 NULL)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    consults = db.relationship("Consult", back_populates="employee")

    def get_id(self) -> str:
        # UserMixin 기본 구현은 self.id 를 찾는데, 우리 PK 컬럼명은 employee_id 라서 직접 오버라이드해야 한다.
        return str(self.employee_id)

    def set_password(self, raw_password: str) -> None:
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, raw_password)
