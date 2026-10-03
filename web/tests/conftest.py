"""웹 테스트 공통 준비. 항상 임시 sqlite DB 를 쓴다 (팀 공용 DB에 테스트 데이터가 쌓이지 않게)."""
import pytest

from app import create_app
from app.extensions import db
from app.models import Employee, EmployeeRole


@pytest.fixture
def app(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/test.db")
    with app.app_context():
        for name, email, role, department in [
            ("김서연", "bank@test.com", EmployeeRole.agent, "은행"),
            ("박지훈", "ins@test.com", EmployeeRole.agent, "보험"),
            ("관리자", "admin@test.com", EmployeeRole.admin, None),
        ]:
            employee = Employee(name=name, email=email, role=role, department=department)
            employee.set_password("test-pass")
            db.session.add(employee)
        db.session.commit()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(app):
    """로그인한 테스트 클라이언트를 돌려주는 함수. 사용: login("bank@test.com")"""
    def _login(email):
        client = app.test_client()
        assert client.post("/login", data={"email": email, "password": "test-pass"}).status_code == 302
        return client
    return _login
