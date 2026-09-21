# API 명세 (web ↔ ai)  — 초안

웹 서버(Flask)가 AI 서버(FastAPI)를 호출합니다. 실제 코드: `ai/app/schemas/chat.py`
AI가 완성되기 전에는 `AI_MOCK_MODE=true` 로 가짜 응답을 받으면서 웹을 개발합니다.

## GET /health
서버 상태 확인. → `{"status": "ok", "mock_mode": true}`

## POST /chat
**요청**
```json
{ "session_id": "abc-123", "message": "대출 만기 연장하려면 어떻게 해야 하나요?" }
```
**응답**
```json
{
  "answer": "…",
  "category": "은행",
  "topic": "대출문의(만기/연장/조회등)",
  "confidence": 0.91,
  "sources": [
    { "doc_id": "21-1_bk_08_000123_001", "category": "은행", "topic": "대출문의(만기/연장/조회등)",
      "score": 0.91, "snippet": "…" }
  ],
  "handoff_needed": false,
  "handoff_reason": null
}
```
| 필드 | 설명 |
|---|---|
| `category` | 판단된 금융 분야: `은행` / `보험` / `증권` (모호하면 null) |
| `confidence` | 분야 판단 확신도 0~1. 낮으면 웹이 "은행/보험 중 어떤 문의인가요?" 를 물을 수 있음 |
| `sources` | RAG 검색 근거 (상담사에게 이관할 때 함께 전달) |
| `handoff_needed` | true 면 웹이 상담사 연결을 제안 (근거 부족, 개인정보 필요, 고객 요청 등) |

## 후속 (필요해지면 추가)
- `POST /summarize` : 상담 요약 (상담사 이관 시 전달)
- `POST /classify` : BERT 분류기 도입 시
