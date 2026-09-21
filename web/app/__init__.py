"""Flask 앱 생성.

실행 (web/ 폴더 안에서):
    flask --app app run --debug --port 5000
"""
import os

from dotenv import load_dotenv
from flask import Flask

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    app.config["AI_SERVER_URL"] = os.getenv("AI_SERVER_URL", "http://localhost:8000")

    from app.routes import auth, chat

    app.register_blueprint(auth.bp)
    app.register_blueprint(chat.bp)
    return app
