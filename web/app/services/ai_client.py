"""web 서버 → AI 서버 호출."""
import requests
from flask import current_app


def ask(session_id: str, message: str, history: list | None = None) -> dict:
    """history: 이번 상담의 직전 대화 [{"role": "user"|"assistant", "content": "..."}] (오래된 순). 후속 질문 이해용."""
    url = current_app.config["AI_SERVER_URL"] + "/chat"
    payload = {"session_id": session_id, "message": message}
    if history:
        payload["history"] = history
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"answer": "죄송합니다. 지금은 AI 상담을 이용할 수 없어요. 상담사 연결을 이용해 주세요.",
                "handoff_needed": True, "handoff_code": "ai_error", "handoff_reason": f"AI 서버 오류: {e.__class__.__name__}"}
