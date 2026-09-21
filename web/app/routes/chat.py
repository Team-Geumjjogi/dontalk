"""채팅 화면 + 질문을 AI 서버로 전달.

TODO(웹 담당): 상담사 화면(agent.py), 상담사 연결(handoff) 흐름, 대화 저장(DB).
"""
import uuid

from flask import Blueprint, jsonify, render_template, request, session

from app.services import ai_client

bp = Blueprint("chat", __name__)


@bp.route("/")
def index():
    session.setdefault("session_id", str(uuid.uuid4()))
    return render_template("chat.html")


@bp.route("/api/chat", methods=["POST"])
def chat():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is empty"}), 400
    session.setdefault("session_id", str(uuid.uuid4()))
    return jsonify(ai_client.ask(session["session_id"], message))
