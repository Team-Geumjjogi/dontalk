"""질문 → (RAG 검색) → (분야 판단) → (LLM 답변) 전체 흐름.

지금은 mock 응답만 돌려줍니다. 담당자가 아래 TODO 를 채워 넣으세요.
"""
from app.core import config
from app.schemas.chat import ChatRequest, ChatResponse, Source


def answer(req: ChatRequest) -> ChatResponse:
    if config.AI_MOCK_MODE:
        return _mock_answer(req)

    # TODO(RAG 담당) : docs = retriever.search(req.message, top_k=5)
    # TODO(RAG 담당) : category, topic, confidence = router.decide(docs)
    # TODO(LLM 담당) : text = llm.generate(context=docs, question=req.message)
    # TODO : confidence/근거가 부족하면 handoff_needed=True
    raise NotImplementedError("실제 RAG/LLM 파이프라인이 아직 연결되지 않았습니다. AI_MOCK_MODE=true 로 실행하세요.")


def _mock_answer(req: ChatRequest) -> ChatResponse:
    """AI가 완성되기 전에 웹 화면을 개발할 수 있도록 하는 가짜 응답."""
    msg = req.message
    if "상담사" in msg or "연결" in msg:
        return ChatResponse(
            answer="상담사 연결을 도와드릴게요.",
            category="은행", topic="대출문의(만기/연장/조회등)", confidence=0.9,
            handoff_needed=True, handoff_reason="고객이 상담사 연결을 요청함",
        )
    return ChatResponse(
        answer=f"[MOCK] '{msg}' 에 대한 가짜 답변입니다. 실제 모델이 연결되면 근거 기반 답변으로 바뀝니다.",
        category="은행", topic="대출문의(만기/연장/조회등)", confidence=0.91,
        sources=[Source(doc_id="mock-001", category="은행", topic="대출문의(만기/연장/조회등)",
                        score=0.91, snippet="(mock) 대출 만기 연장 안내...")],
    )
