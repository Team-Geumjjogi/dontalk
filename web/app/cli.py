"""flask 커스텀 커맨드. 상담사/관리자는 회원가입 화면이 없어서, 계정은 이 명령어로 미리 만들어둔다.

사용 (web/ 폴더 안에서):
    flask --app app create-employee --name 김서연 --email agent1@dontalk.com --password test1234 --role agent --department 은행
    flask --app app create-employee --name 관리자 --email admin@dontalk.com --password test1234 --role admin
    flask --app app reset-db --yes      # 웹 전용 테이블만 지우고 새 구조로 다시 만든다 (계정도 사라지니 다시 만들 것)
"""
import click

from app.extensions import db
from app.models import CATEGORIES, Employee, EmployeeRole


def register_cli(app):
    @app.cli.command("create-employee")
    @click.option("--name", required=True)
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--role", type=click.Choice(["agent", "admin"]), required=True)
    @click.option("--department", type=click.Choice(CATEGORIES), default=None, help="담당 분야 (상담사는 필수, 관리자는 생략)")
    def create_employee(name, email, password, role, department):
        if role == "agent" and not department:
            raise click.UsageError("상담사는 --department(은행/보험/증권)가 필요합니다. 분야별 대기 큐가 이 값으로 나뉩니다.")
        if role == "admin" and department:
            raise click.UsageError("관리자는 --department 를 지정하지 않습니다.")
        if Employee.query.filter_by(email=email).first():
            click.echo(f"이미 존재하는 이메일입니다: {email}")
            return

        employee = Employee(name=name, email=email, role=EmployeeRole(role), department=department)
        employee.set_password(password)  # 여기서 scrypt로 해싱됨. 평문은 저장 안 됨.
        db.session.add(employee)
        db.session.commit()
        click.echo(f"생성 완료: {employee.name} ({employee.role.value}{', ' + department if department else ''}) - {employee.email}")

    @app.cli.command("reset-db")
    @click.option("--yes", is_flag=True, help="확인 없이 진행 (이 옵션이 없으면 아무것도 하지 않는다)")
    def reset_db(yes):
        """웹 전용 테이블(customer/consult/consult_transfer/employee/message)을 삭제하고 새 구조로 다시 만든다.

        모델에 정의된 테이블만 대상이다. 같은 DB의 RAG 지식베이스(financial_consulting_qa)는 모델에 없어서 건드리지 않는다.
        개발 단계에서 컬럼을 바꿨을 때 쓴다 (db.create_all() 은 이미 있는 테이블의 컬럼 변경을 반영하지 않기 때문).
        """
        tables = sorted(db.metadata.tables)
        if not yes:
            click.echo(f"삭제 후 재생성할 테이블: {', '.join(tables)}\n실행하려면 --yes 를 붙이세요.")
            return
        db.drop_all()
        db.create_all()
        click.echo(f"재생성 완료: {', '.join(tables)}")
