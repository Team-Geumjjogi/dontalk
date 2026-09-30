"""flask 커스텀 커맨드. 상담사/관리자는 회원가입 화면이 없어서, 계정은 이 명령어로 미리 만들어둔다.

사용 (web/ 폴더 안에서):
    flask --app app create-employee --name 김서연 --email agent1@dontalk.com --password test1234 --role agent --department 은행
    flask --app app create-employee --name 관리자 --email admin@dontalk.com --password test1234 --role admin
"""
import click

from app.extensions import db
from app.models import Employee, EmployeeRole


def register_cli(app):
    @app.cli.command("create-employee")
    @click.option("--name", required=True)
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--role", type=click.Choice(["agent", "admin"]), required=True)
    @click.option("--department", default=None, help="은행/보험/증권 (상담사만 해당, 관리자는 생략)")
    def create_employee(name, email, password, role, department):
        if Employee.query.filter_by(email=email).first():
            click.echo(f"이미 존재하는 이메일입니다: {email}")
            return

        employee = Employee(name=name, email=email, role=EmployeeRole(role), department=department)
        employee.set_password(password)  # 여기서 scrypt로 해싱됨. 평문은 저장 안 됨.
        db.session.add(employee)
        db.session.commit()
        click.echo(f"생성 완료: {employee.name} ({employee.role.value}) - {employee.email}")
