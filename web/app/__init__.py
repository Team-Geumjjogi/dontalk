"""Flask 앱 생성.

실행 (web/ 폴더 안에서):
    uv run flask --app app run --debug --port 5001
"""
import os

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy.engine import URL

from app.extensions import db, login_manager
from app.services.business_hours import format_kst

load_dotenv()


def _database_uri() -> URL:
    """웹 전용 테이블(customer/consult/employee/message)은 팀 공용 DB(.env 의 DB_*)에 둔다.

    같은 DB 안에 RAG 지식베이스(financial_consulting_qa)도 있지만 테이블이 다르다. 이전의 로컬 DB(POSTGRES_*, DATABASE_URL)는 쓰지 않는다.
    psycopg(v3) 드라이버를 쓰고, 비밀번호에 특수문자가 있어도 안전하도록 문자열이 아니라 URL 객체로 조립한다.
    """
    missing = [k for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f".env 에 공용 DB 접속 정보가 없습니다: {', '.join(missing)}")
    query = {"sslmode": os.getenv("DB_SSLMODE", "require")}
    if os.getenv("DB_SSLNEGOTIATION", "direct"):
        query["sslnegotiation"] = os.getenv("DB_SSLNEGOTIATION", "direct")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]), database=os.environ["DB_NAME"],
        query=query,
    )


def create_app(database_uri: str | None = None) -> Flask:
    """database_uri: 테스트에서 공용 DB 대신 임시 DB(sqlite 등)를 쓰려고 직접 넘기는 용도. 보통은 비워둔다."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    app.config["AI_SERVER_URL"] = os.getenv("AI_SERVER_URL", "http://localhost:8000")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri or _database_uri()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}  # 원격 DB 연결이 끊겨 있으면 자동으로 다시 연결
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.jinja_env.filters["kst"] = format_kst  # {{ consult.created_at|kst }}

    db.init_app(app)

    from app import models  # noqa: F401  (db.create_all() 이 모델을 찾으려면 import 필요)

    with app.app_context():
        # Spring의 ddl-auto: update 와 같은 방식 — 모델에 정의됐는데 DB에 없는 테이블만 만들어준다.
        # 이미 있는 테이블(financial_consulting_qa 포함)은 절대 건드리지 않고, 기존 테이블의 컬럼 변경도 감지하지 않는다
        # (컬럼을 바꿨다면 개발 단계에선 그냥 테이블을 지우고 다시 만드는 게 제일 간단하다).
        db.create_all()

    # 상담사/관리자 로그인 (고객은 로그인 없음). login_view: 비로그인 상태로 보호된 페이지에 접근하면
    # 여기로 redirect 시켜준다 (Spring Security의 로그인 페이지 리다이렉트와 같은 동작).
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(employee_id: str):
        # 세션에 저장된 id로 실제 Employee row를 다시 불러오는 콜백 (Spring의 UserDetailsService.loadUserByUsername 과 같은 역할)
        return models.Employee.query.get(int(employee_id))

    from app.routes import admin, agent, auth, chat, main

    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(chat.bp)
    app.register_blueprint(agent.bp)
    app.register_blueprint(admin.bp)

    from app.cli import register_cli
    register_cli(app)

    return app
