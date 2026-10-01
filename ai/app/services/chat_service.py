"""질문 → (RAG 검색) → (분야 판단) → (LLM 답변) → (이관 판단) 전체 흐름. 질문 한 건 단위(단일턴).

흐름
  1. 공용 DB 에서 유사 상담 Top-K 검색 → 분야/주제/확신도 판단
  2. 아래 경우는 LLM 을 거치지 않고 상담사 이관 (handoff_needed=True)
       - 상담사 연결 요청 / 계좌 해지·이체 같은 실제 처리 요청 (2.4B base 는 프롬프트 지시를 안 따라서 규칙으로 처리)
       - 검색 근거가 약함(최고 유사도 < RAG_MIN_SIMILARITY) / 분야 확신도 낮음(< RAG_MIN_CONFIDENCE)
       - 검색 또는 LLM 오류
  3. 그 외에는 검색된 문서를 근거로 LLM 이 답변

.env (모두 선택, 없으면 기본값)
  LLM_BACKEND          ollama(기본, 로컬 개발) | transformers(GPU 서버, 팀원 model.py + 분야별 어댑터)
  RAG_MIN_SIMILARITY   기본 0.55  (업무 질문 15개 최소 0.63 / 업무 밖·경계 질문 최대 0.51 로 정한 초기값)
  RAG_MIN_CONFIDENCE   기본 0.6
"""
import logging
import os
import re
from typing import List, Optional

from app.core import config
from app.rag import router
from app.schemas.chat import ChatRequest, ChatResponse, Source

log = logging.getLogger("app.chat")

LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").strip().lower()
MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.55"))
MIN_CONFIDENCE = float(os.getenv("RAG_MIN_CONFIDENCE", "0.6"))

MSG_CONTACT = "상담사 연결을 도와드릴게요."
MSG_ACTION = "계좌 해지·이체 같은 실제 처리는 상담사가 직접 도와드릴 수 있어요. 상담사 연결을 도와드릴게요."
MSG_NO_BASIS = "죄송합니다. 문의하신 내용은 제가 정확히 안내드리기 어려워요. 상담사 연결을 도와드릴게요."
MSG_ERROR = "죄송합니다. 지금은 답변을 만들 수 없어요. 상담사 연결을 도와드릴게요."

# --- 규칙 기반 판단 (휴리스틱이라 오탐/미탐이 있을 수 있음. 써 보면서 보완) ---
_CONTACT = re.compile(r"(상담사|상담원|직원|담당자).{0,12}(연결|통화|바꿔|전화)|(연결|통화).{0,8}(상담사|상담원|직원|담당자)")
_ACTION_VERB = "삭제|해지|해약|개설|이체|송금|취소|변경|신청|등록|정지|해제|탈퇴|재발급|출금|입금|연장|가입|한도"
_REQUEST_END = r"(?:해|바꿔|올려|내려|풀어|지워|막아|없애|처리해|진행해)\s*(?:주세요|주시|줘|줄래|달라|주실|주라|드려)|부탁"
_ACTION = re.compile(rf"(?:{_ACTION_VERB}).{{0,12}}(?:{_REQUEST_END})")
_INFO_CUE = re.compile(r"방법|절차|어떻게|알려|설명|문의|궁금|가능한|되나요|인가요|서류|조건|언제|얼마")
_MASK = re.compile(r"●+")  # 공용 DB 문서의 개인정보 마스킹 표시


def is_contact_request(message: str) -> bool:
    return bool(_CONTACT.search(message))


def is_action_request(message: str) -> bool:
    """'해지해 주세요' 같은 처리 요청이면 True. '해지 방법 알려주세요' 같은 정보 문의는 False."""
    return bool(_ACTION.search(message)) and not _INFO_CUE.search(message)


def _mask(text: str) -> str:
    """●● 같은 마스킹 표시를 [비공개]로 바꿔서 LLM 이 그대로 따라 쓰지 않게 한다."""
    return _MASK.sub("[비공개]", text)


def _mask_doc(doc: dict) -> dict:
    return {k: _mask(v) if isinstance(v, str) else v for k, v in doc.items()}


# --- 외부 연동 (무거운 import 는 실제로 쓸 때만. 테스트에서는 이 함수들을 바꿔 끼운다) ---
def _search(message: str) -> List[dict]:
    from app.rag import retriever

    return retriever.search(message)


def _generate(message: str, category: Optional[str], docs: List[dict]) -> str:
    clean = [_mask_doc(d) for d in docs]
    if LLM_BACKEND == "transformers":
        from app.llm import model  # 팀원 model.py (HF + 분야별 LoRA). GPU 서버에서 사용

        rag = "\n\n".join(d.get("full_source") or "" for d in clean)
        return model.answer(category, f"고객 질문 : {message}\nRAG 결과: {rag}")
    from app.llm import ollama_client

    return ollama_client.generate(message, clean)


def warm_up() -> None:
    """서버 시작 때 모델/DB 를 미리 준비해서 첫 질문이 느려지지 않게 한다. 실패해도 서버는 뜬다."""
    try:
        from app.rag import retriever

        retriever.warm_up()
        if LLM_BACKEND == "transformers":
            from app.llm import model

            model.load_model()
        log.info("워밍업 완료 (backend=%s)", LLM_BACKEND)
    except Exception:
        log.exception("워밍업 실패 - 첫 요청 때 다시 시도합니다")


def _sources(docs: List[dict]) -> List[Source]:
    return [
        Source(
            doc_id=str(d["qa_id"]),
            category=d.get("consulting_category") or "",
            topic=d.get("consulting_topic") or "",
            score=round(d["similarity"], 4),
            snippet=(d.get("question") or d.get("full_source") or "")[:120],
        )
        for d in docs
    ]


def answer(req: ChatRequest) -> ChatResponse:
    if config.AI_MOCK_MODE:
        return _mock_answer(req)

    message = req.message.strip()

    docs: List[dict] = []
    search_error: Optional[Exception] = None
    try:
        docs = _search(message)
    except Exception as e:  # DB 연결/임베딩 오류 등. 서비스는 계속하고 이관으로 처리
        log.exception("RAG 검색 실패")
        search_error = e

    category, topic, confidence = router.decide(docs)
    best = docs[0]["similarity"] if docs else 0.0
    grounded = best >= MIN_SIMILARITY
    if not grounded:  # 근거가 약하면 분야 판단도 믿을 수 없다
        category, topic, confidence = None, None, 0.0
    sources = _sources(docs) if grounded else []

    def handoff(text: str, reason: str) -> ChatResponse:
        return ChatResponse(
            answer=text, category=category, topic=topic, confidence=confidence,
            sources=sources, handoff_needed=True, handoff_reason=reason,
        )

    if is_contact_request(message):
        return handoff(MSG_CONTACT, "고객이 상담사 연결을 요청함")
    if is_action_request(message):
        return handoff(MSG_ACTION, "실제 처리가 필요한 요청 (AI는 안내만 가능)")
    if search_error is not None:
        return handoff(MSG_ERROR, f"검색 오류: {search_error.__class__.__name__}")
    if not grounded:
        return handoff(MSG_NO_BASIS, f"관련 상담 근거 부족 (최고 유사도 {best:.2f} < {MIN_SIMILARITY})")
    if confidence < MIN_CONFIDENCE:
        return handoff(MSG_NO_BASIS, f"분야 판단 확신도 낮음 ({confidence:.2f} < {MIN_CONFIDENCE})")

    try:
        text = _generate(message, category, docs)
    except Exception as e:
        log.exception("LLM 답변 생성 실패")
        return handoff(MSG_ERROR, f"LLM 오류: {e.__class__.__name__}")
    if not text:
        return handoff(MSG_ERROR, "LLM 이 빈 답변을 반환함")

    return ChatResponse(answer=text, category=category, topic=topic, confidence=confidence, sources=sources)


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
