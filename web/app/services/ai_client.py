"""web 서버 → AI 서버 호출."""
import requests
from flask import current_app

# 타임아웃 계층: 브라우저(chat.js) 90초 > 웹→AI 70초 > AI 서버 안의 DB 검색 최대 ≈22초 + LLM 40초
AI_TIMEOUT_SECONDS = 70


def ask(session_id: str, message: str, history: list | None = None) -> dict:
    """history: 이번 상담의 직전 대화 [{"role": "user"|"assistant", "content": "..."}] (오래된 순). 후속 질문 이해용."""
    url = current_app.config["AI_SERVER_URL"] + "/chat"
    payload = {"session_id": session_id, "message": message}
    if history:
        payload["history"] = history
    try:
        r = requests.post(url, json=payload, timeout=AI_TIMEOUT_SECONDS)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"answer": "죄송합니다. 지금은 AI 상담을 이용할 수 없어요. 상담사 연결을 이용해 주세요.",
                "handoff_needed": True, "handoff_code": "ai_error", "handoff_reason": f"AI 서버 오류: {e.__class__.__name__}"}
