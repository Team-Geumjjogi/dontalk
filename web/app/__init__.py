"""Flask 앱 생성.

실행 (web/ 폴더 안에서):
    uv run flask --app app run --debug --port 5001
"""
import os

from dotenv import load_dotenv
from flask import Flask

from app.extensions import db, login_manager

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    app.config["AI_SERVER_URL"] = os.getenv("AI_SERVER_URL", "http://localhost:8000")

    # DATABASE_URL은 docker-compose로 띄운 pgvector용 Postgres를 그대로 재사용한다 (AI 쪽과 같은 DB, 다른 테이블).
    # psycopg2가 아니라 psycopg(v3)를 쓰고 있어서, SQLAlchemy가 psycopg3 드라이버를 쓰도록 스킴을 바꿔준다.
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from app import models  # noqa: F401  (db.create_all() 이 모델을 찾으려면 import 필요)

    with app.app_context():
        # Spring의 ddl-auto: update 와 같은 방식 — 모델에 정의됐는데 DB에 없는 테이블만 만들어준다.
        # 이미 있는 테이블(document_chunk 포함)은 절대 건드리지 않고, 기존 테이블의 컬럼 변경도 감지하지 않는다
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

    from app.routes import auth, chat

    app.register_blueprint(auth.bp)
    app.register_blueprint(chat.bp)

    from app.cli import register_cli
    register_cli(app)

    return app
