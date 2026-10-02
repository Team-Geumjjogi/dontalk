# API 명세 (web ↔ ai)  — 초안

웹 서버(Flask)가 AI 서버(FastAPI)를 호출합니다. 실제 코드: `ai/app/schemas/chat.py`
AI가 완성되기 전에는 `AI_MOCK_MODE=true` 로 가짜 응답을 받으면서 웹을 개발합니다.

## GET /health
서버 상태 확인. → `{"status": "ok", "mock_mode": true}`

## POST /chat
**요청**
```json
{
  "session_id": "abc-123",
  "message": "그럼 수수료는 얼마예요?",
  "history": [
    { "role": "user", "content": "대출 만기 연장하려면 어떻게 해야 하나요?" },
    { "role": "assistant", "content": "앱의 대출관리 메뉴에서 신청하실 수 있어요." }
  ]
}
```
| 필드 | 설명 |
|---|---|
| `history` | **선택.** 이번 상담의 직전 대화(오래된 순, 웹이 최근 6건 정도 전달). `role` 은 고객 `user` / AI `assistant`. 없으면 질문 한 건으로만 처리. 짧은 후속 질문("그럼 수수료는요?")을 이해하는 데 쓰입니다. |

**응답**
```json
{
  "answer": "…",
  "category": "은행",
  "topic": "대출문의(만기/연장/조회등)",
  "confidence": 0.91,
  "sources": [
    { "doc_id": "21-1_bk_08_000123_001", "category": "은행", "topic": "대출문의(만기/연장/조회등)",
      "score": 0.91, "snippet": "…", "follow_up_question": "…", "output": "…" }
  ],
  "handoff_needed": false,
  "handoff_code": null,
  "handoff_reason": null
}
```
| 필드 | 설명 |
|---|---|
| `category` | 판단된 금융 분야: `은행` / `보험` / `증권` (모호하면 null) |
| `confidence` | 분야 판단 확신도 0~1. 낮으면 웹이 "은행/보험 중 어떤 문의인가요?" 를 물을 수 있음 |
| `sources` | RAG 검색 근거 (상담사에게 이관할 때 함께 전달). `follow_up_question`(예상 꼬리질문)과 `output`(예상 종합 답변, 최대 800자)은 상담사 화면에 보여준다 |
| `handoff_needed` | true 면 웹이 상담사 연결을 제안 (근거 부족, 개인정보 필요, 고객 요청 등) |
| `handoff_code` | 이관 사유 코드(웹이 사유별로 저장/집계): `contact_request`(상담사 연결 요청) / `action_request`(해지·이체 같은 처리 요청) / `no_basis`(답변 근거 없음) / `low_confidence`(분야 판단 불확실) / `ai_error`(AI 오류) |
| `handoff_reason` | 사람이 읽는 상세 사유 (예: "관련 상담 근거 부족 (최고 유사도 0.50 < 0.55)") |

## 후속 (필요해지면 추가)
- `POST /summarize` : 상담 요약 (상담사 이관 시 전달)
- `POST /classify` : BERT 분류기 도입 시
