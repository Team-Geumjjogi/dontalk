"""web 서버 → AI 서버 호출."""
import requests
from flask import current_app


def ask(session_id: str, message: str) -> dict:
    url = current_app.config["AI_SERVER_URL"] + "/chat"
    try:
        r = requests.post(url, json={"session_id": session_id, "message": message}, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"answer": "죄송합니다. 지금은 AI 상담을 이용할 수 없어요. 상담사 연결을 이용해 주세요.",
                "handoff_needed": True, "handoff_reason": f"AI 서버 오류: {e.__class__.__name__}"}
