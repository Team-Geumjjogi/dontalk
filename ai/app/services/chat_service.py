"""질문 → (RAG 검색) → (분야 판단) → (LLM 답변) → (이관 판단) 전체 흐름.

흐름
  0. 인사/감사 같은 잡담은 검색·LLM 없이 짧게 응대
  1. 공용 DB 에서 유사 상담 Top-K 검색 → 분야/주제/확신도 판단
       (이전 대화가 있고 "그럼 수수료는요?" 같은 짧은 후속 질문이면, 직전 고객 질문을 붙여서 검색)
  2. 아래 경우는 LLM 을 거치지 않고 상담사 이관 (handoff_needed=True)
       - 상담사 연결 요청 / 계좌 해지·이체 같은 실제 처리 요청 (2.4B base 는 프롬프트 지시를 안 따라서 규칙으로 처리)
       - 검색 근거가 약함(최고 유사도 < RAG_MIN_SIMILARITY) / 분야 확신도 낮음(< RAG_MIN_CONFIDENCE)
       - 검색 또는 LLM 오류
     단, 금융과 무관한 질문(최고 유사도 < RAG_OUT_OF_SCOPE_BELOW, 예: 날씨/잡담)은 이관하지 않고 "금융 상담만 가능" 안내만 한다
  3. 그 외에는 검색된 문서를 근거로 LLM 이 답변 → 마크다운 제거, [비공개] 문장 정리, 길이 제한(ANSWER_MAX_CHARS)

.env (모두 선택, 없으면 기본값)
  
  RAG_LLM_DOCS         기본 1 (LLM 프롬프트에 넣는 참고 문서 수. 검색·분야 판단·상담사 화면은 RAG_TOP_K 건 전체 사용)
  RAG_MIN_SIMILARITY   기본 0.55  (업무 질문 15개 최소 0.63 / 업무 밖·경계 질문 최대 0.51 로 정한 초기값)
  RAG_MIN_CONFIDENCE   기본 0.6
  RAG_OUT_OF_SCOPE_BELOW 기본 0.45 (25개 질문 조사: 업무 밖 질문 최대 0.43, 업무 질문 최소 0.63)
  ANSWER_MAX_CHARS     기본 500 (2.4B 가 프롬프트의 "3~5문장"을 무시하고 길게 쓰는 것을 코드로 제한)
"""
import logging
import os
import re
import time
from typing import List, Optional


from app.core import config
from app.rag import router
from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.llm import vllm_client


log = logging.getLogger("app.chat")


# LLM 에 넣는 참고 문서 수. 튜닝 모델이 RAG 없이(질의+답변만) 학습돼서 여러 문서 중 맞는 걸 고르지 못하고 프롬프트 맨 뒤 문서를 따라간다.
# 실측(크롤링 FAQ 24개, FAQ 질문 그대로): 5건 → 정답 문서를 따라간 답변 0/24, 1위만 → 20/24. 일반 질문 25개도 1위만 줄 때 적절한 답이 4개에서 12개로 늘었다.
# 그래서 지금은 1위만 준다. RAG 를 포함해 다시 학습한 모델로 바꾸면 이 값을 올린다.
LLM_DOC_COUNT = max(1, int(os.getenv("RAG_LLM_DOCS", "1")))
MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.55"))
MIN_CONFIDENCE = float(os.getenv("RAG_MIN_CONFIDENCE", "0.6"))
OUT_OF_SCOPE_BELOW = float(os.getenv("RAG_OUT_OF_SCOPE_BELOW", "0.45"))
ANSWER_MAX_CHARS = int(os.getenv("ANSWER_MAX_CHARS", "500"))

MAX_HISTORY_TURNS = 6      # 후속 질문 검색 보강에 쓰는 이전 대화 개수 (LLM 프롬프트에는 이전 대화를 넣지 않는다)
MAX_TURN_CHARS = 500       # 이전 발화 1건당 최대 글자 수
SOURCE_OUTPUT_MAX = 800    # 상담사 화면용 근거 문서의 종합 답변 최대 글자 수
FOLLOW_UP_MAX_CHARS = 15   # 이 길이 이하면 후속 질문으로 보고 직전 질문을 붙여서 검색
ERROR_DETAIL_MAX = 200     # 상담사 화면용 handoff_reason 에 붙이는 오류 메시지 최대 글자 수

MSG_CONTACT = "상담사 연결을 도와드릴게요."
MSG_ACTION = "계좌 해지·이체 같은 실제 처리는 상담사가 직접 도와드릴 수 있어요. 상담사 연결을 도와드릴게요."
MSG_NO_BASIS = "죄송합니다. 문의하신 내용은 제가 정확히 안내드리기 어려워요. 상담사 연결을 도와드릴게요."
MSG_ERROR = "죄송합니다. 지금은 답변을 만들 수 없어요. 상담사 연결을 도와드릴게요."
MSG_REDACTED = "정확한 금액이나 세부 내용은 상담사에게 확인해 주세요."
MSG_OUT_OF_SCOPE = ("저는 은행·보험·증권 관련 상담을 도와드리는 AI예요. 금융 관련해서 궁금한 점을 말씀해 주시면 안내해 드릴게요. "
                    "직접 상담이 필요하시면 상단의 '상담사 연결'을 눌러 주세요.")
MSG_TRUNCATED = "더 자세한 내용은 상담사에게 확인해 주세요."
MSG_GREETING = "안녕하세요! 금융 상담 도우미 돈톡입니다. 은행·보험·증권 관련해서 궁금한 점을 편하게 말씀해 주세요."
MSG_THANKS = "도움이 되었다니 기쁩니다. 더 궁금한 점이 있으면 언제든 말씀해 주세요."

# --- 규칙 기반 판단 (휴리스틱이라 오탐/미탐이 있을 수 있음. 써 보면서 보완) ---
_CONTACT = re.compile(
    r"(상담사|상담원).{0,12}(연결|통화|바꿔|전화|얘기|이야기|대화)"
    r"|(직원|담당자|사람).{0,12}(연결|통화|바꿔|전화|(?:얘기|이야기|대화)\s*(?:하고\s*싶|할래|하게\s*해))"
    r"|(연결|통화).{0,8}(상담사|상담원|직원|담당자)"
)
_ACTION_VERB = "삭제|해지|해약|개설|이체|송금|취소|변경|신청|등록|정지|해제|탈퇴|재발급|출금|입금|연장|가입|한도"
_REQUEST_END = r"(?:해|바꿔|올려|내려|풀어|지워|막아|없애|처리해|진행해)\s*(?:주세요|주시|줘|줄래|달라|주실|주라|드려)|부탁"
_ACTION = re.compile(rf"(?:{_ACTION_VERB}).{{0,12}}(?:{_REQUEST_END})")
_INFO_CUE = re.compile(r"방법|절차|어떻게|알려|설명|문의|궁금|가능한|되나요|인가요|서류|조건|언제|얼마")
_GREETING = re.compile(r"안녕|안녕하세요|안녕하십니까|하이|헬로|반갑습니다|반가워요|처음뵙겠습니다")
_THANKS = re.compile(r"감사합니다|감사해요|고맙습니다|고마워요|고마워|땡큐|수고하세요|수고하셨습니다")
_FOLLOW_UP_START = re.compile(r"^(그럼|그러면|그리고|그럼요|그건|그거|그게|이건|이거|그 경우|그때|아니면|또|다른)")
_MASK = re.compile(r"●+")  # 공용 DB 문서의 개인정보 마스킹 표시
_MD_SYMBOLS = re.compile(r"\*\*|__|`")
_MD_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.M)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])(?<!\d\.)\s+")  # 목록 번호("3.")의 마침표는 문장 끝으로 보지 않는다


def is_contact_request(message: str) -> bool:
    return bool(_CONTACT.search(message))


def is_action_request(message: str) -> bool:
    """'해지해 주세요' 같은 처리 요청이면 True. '해지 방법 알려주세요' 같은 정보 문의는 False."""
    return bool(_ACTION.search(message)) and not _INFO_CUE.search(message)


def small_talk_reply(message: str) -> Optional[str]:
    """인사/감사 한마디면 응대 문구, 아니면 None. 질문이 섞여 있으면 (예: '안녕하세요 대출 연장이요') None."""
    compact = re.sub(r"[\s!.?~,]+", "", message)
    if _GREETING.fullmatch(compact):
        return MSG_GREETING
    if _THANKS.fullmatch(compact):
        return MSG_THANKS
    return None


def _mask(text: str) -> str:
    """●● 같은 마스킹 표시를 [비공개]로 바꿔서 LLM 이 그대로 따라 쓰지 않게 한다."""
    return _MASK.sub("[비공개]", text)


def _mask_doc(doc: dict) -> dict:
    return {k: _mask(v) if isinstance(v, str) else v for k, v in doc.items()}


def clean_answer(text: str) -> str:
    """LLM 답변을 고객 화면(순수 텍스트)에 맞게 정리한다.
    - 마크다운 기호(**, 제목 #, `) 제거
    - [비공개]가 들어간 문장은 '상담사에게 확인' 안내 한 번으로 대체
    """
    text = _MD_HEADING.sub("", _MD_SYMBOLS.sub("", text))
    lines, redacted = [], False
    for line in text.splitlines():
        kept = []
        for sentence in _SENTENCE_SPLIT.split(line):
            if "[비공개]" not in sentence:
                kept.append(sentence)
            elif not redacted:
                kept.append(MSG_REDACTED)
                redacted = True
        lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def limit_answer(text: str, max_chars: int = ANSWER_MAX_CHARS) -> str:
    """답변이 max_chars 를 넘으면 문장 단위로 잘라서 끊긴 문장이 없게 하고, 상담사 확인 안내를 덧붙인다.
    첫 문장부터 너무 길면 글자 수로 자른다."""
    if len(text) <= max_chars:
        return text
    lines, used, truncated = [], 0, False
    for line in text.splitlines():
        kept = []
        for sentence in _SENTENCE_SPLIT.split(line):
            if used + len(sentence) > max_chars:
                truncated = True
                break
            kept.append(sentence)
            used += len(sentence) + 1
        lines.append(" ".join(kept))
        if truncated:
            break
    result = "\n".join(lines).strip() or text[:max_chars].rstrip() + "…"
    return f"{result}\n{MSG_TRUNCATED}"


# --- 다중턴 ---
def _recent_history(req: ChatRequest) -> List[dict]:
    """요청의 이전 대화를 최근 N건, 발화당 길이 제한으로 줄여서 LLM 입력 형태로 바꾼다."""
    turns = [{"role": t.role, "content": t.content.strip()[:MAX_TURN_CHARS]} for t in req.history if t.content.strip()]
    return turns[-MAX_HISTORY_TURNS:]


def find_docs(message: str, history: List[dict]) -> List[dict]:
    """질문에 맞는 근거 문서를 찾는다. 짧은 후속 질문은 직전 질문을 붙여서 검색하되, 직전 질문과 무관한 질문까지 붙지 않게 한다.

    "오늘 서울 날씨 어때요?"처럼 짧아도 후속 질문이 아닌 경우가 있는데, 직전 질문을 붙이면 유사도가 0.7 이상으로 올라가서
    업무 밖 질문을 가려낼 수 없다. 그래서 참조어("그럼/그건…")가 없는 짧은 질문은 먼저 단독으로 검색하고,
    단독 유사도가 업무 밖 수준(< OUT_OF_SCOPE_BELOW)이면 합치지 않는다. (단독 유사도 실측: 진짜 후속 질문 0.46~0.83 / 업무 밖 질문 0.29~0.44)
    """
    query = build_search_query(message, history)
    if query == message:
        return _search(message)
    if not _FOLLOW_UP_START.match(message):
        alone = _search(message)
        if not alone or alone[0]["similarity"] < OUT_OF_SCOPE_BELOW:
            return alone
    return _search(query)


def build_search_query(message: str, history: List[dict]) -> str:
    """검색에 쓸 문장. 짧은 후속 질문('그럼 수수료는요?')은 그 한 줄로는 검색이 안 되므로 직전 고객 질문을 앞에 붙인다."""
    last_user = next((t["content"] for t in reversed(history) if t["role"] == "user"), None)
    if last_user and (len(message) <= FOLLOW_UP_MAX_CHARS or _FOLLOW_UP_START.match(message)):
        return f"{last_user} {message}"
    return message


# --- 외부 연동 (무거운 import 는 실제로 쓸 때만. 테스트에서는 이 함수들을 바꿔 끼운다) ---
def _search(query: str) -> List[dict]:
    from app.rag import retriever

    return retriever.search(query)


def _generate(message: str, category: Optional[str], docs: List[dict]) -> str:
    clean = [_mask_doc(d) for d in docs[:LLM_DOC_COUNT]]  # docs 는 유사도 내림차순이라 앞쪽이 가장 관련 높은 문서
    question = vllm_client.build_question(message, clean)
    return vllm_client.generate_answer(category, question)


def warm_up() -> None:
    """서버 시작 때 모델/DB 를 미리 준비해서 첫 질문이 느려지지 않게 한다. 실패해도 서버는 뜬다."""
    try:
        from app.rag import retriever

        retriever.warm_up()
        log.info("워밍업 완료")
    except Exception:
        log.exception("워밍업 실패 - 첫 요청 때 다시 시도합니다")


def _sources(docs: List[dict]) -> List[Source]:
    return [
        Source(
            doc_id=str(d["doc_id"]),
            category=d.get("consulting_category") or "",
            topic=d.get("consulting_topic") or "",
            score=round(d["similarity"], 4),
            snippet=(d.get("question") or "")[:120],
            follow_up_question=d.get("follow_up_question"),
            output=(d.get("output") or "")[:SOURCE_OUTPUT_MAX] or None,
        )
        for d in docs
    ]


def answer(req: ChatRequest) -> ChatResponse:
    """질문 하나를 처리한다. 검색/LLM 소요 시간을 로그로 남겨서 느릴 때 어디가 원인인지 바로 보이게 한다."""
    if config.AI_MOCK_MODE:
        return _mock_answer(req)

    started = time.perf_counter()
    timings: dict = {}
    response = _answer(req, timings)
    outcome = f"이관({response.handoff_code})" if response.handoff_needed else "답변"
    log.info("chat %s | 검색 %.2fs | LLM %.2fs | 전체 %.2fs | 최고유사도 %s",
             outcome, timings.get("search", 0), timings.get("llm", 0), time.perf_counter() - started, timings.get("best", "-"))
    return response


def _error_reason(prefix: str, error: Exception) -> str:
    """Build the counselor-facing handoff_reason: error type plus a short single-line message.

    Never put this text in the customer-facing answer; the message can contain internal addresses.
    """
    detail = " ".join(str(error).split())[:ERROR_DETAIL_MAX]
    if not detail:
        return f"{prefix}: {error.__class__.__name__}"
    return f"{prefix}: {error.__class__.__name__}: {detail}"


def _answer(req: ChatRequest, timings: dict) -> ChatResponse:
    message = req.message.strip()

    reply = small_talk_reply(message)
    if reply:
        return ChatResponse(answer=reply)

    history = _recent_history(req)
    docs: List[dict] = []
    search_error: Optional[Exception] = None
    step = time.perf_counter()
    try:
        docs = find_docs(message, history)
    except Exception as e:  # DB 연결/임베딩 오류 등. 서비스는 계속하고 이관으로 처리
        log.exception("RAG 검색 실패")
        search_error = e
    timings["search"] = time.perf_counter() - step

    category, topic, confidence = router.decide(docs)
    best = docs[0]["similarity"] if docs else 0.0
    timings["best"] = f"{best:.2f}"
    grounded = best >= MIN_SIMILARITY
    if not grounded:  # 근거가 약하면 분야 판단도 믿을 수 없다
        category, topic, confidence = None, None, 0.0
    sources = _sources(docs) if grounded else []

    def handoff(text: str, code: str, reason: str) -> ChatResponse:
        return ChatResponse(
            answer=text, category=category, topic=topic, confidence=confidence, sources=sources,
            handoff_needed=True, handoff_code=code, handoff_reason=reason,
        )

    if is_contact_request(message):
        return handoff(MSG_CONTACT, "contact_request", "고객이 상담사 연결을 요청함")
    if is_action_request(message):
        return handoff(MSG_ACTION, "action_request", "실제 처리가 필요한 요청 (AI는 안내만 가능)")
    if search_error is not None:
        return handoff(MSG_ERROR, "ai_error", _error_reason("검색 오류", search_error))
    if best < OUT_OF_SCOPE_BELOW:  # 날씨/잡담처럼 금융과 무관한 질문: 상담사에게 넘기지 않고 안내만 한다
        return ChatResponse(answer=MSG_OUT_OF_SCOPE)
    if not grounded:
        return handoff(MSG_NO_BASIS, "no_basis", f"관련 상담 근거 부족 (최고 유사도 {best:.2f} < {MIN_SIMILARITY})")
    if confidence < MIN_CONFIDENCE:
        return handoff(MSG_NO_BASIS, "low_confidence", f"분야 판단 확신도 낮음 ({confidence:.2f} < {MIN_CONFIDENCE})")

    step = time.perf_counter()
    try:
        text = limit_answer(clean_answer(_generate(message, category, docs)))
    except Exception as e:
        log.exception("LLM 답변 생성 실패")
        return handoff(MSG_ERROR, "ai_error", _error_reason("LLM 오류", e))
    finally:
        timings["llm"] = time.perf_counter() - step
    if not text:
        return handoff(MSG_ERROR, "ai_error", "LLM 이 빈 답변을 반환함")

    return ChatResponse(answer=text, category=category, topic=topic, confidence=confidence, sources=sources)


def _mock_answer(req: ChatRequest) -> ChatResponse:
    """AI가 완성되기 전에 웹 화면을 개발할 수 있도록 하는 가짜 응답."""
    msg = req.message
    if "상담사" in msg or "연결" in msg:
        return ChatResponse(
            answer="상담사 연결을 도와드릴게요.",
            category="은행", topic="대출문의(만기/연장/조회등)", confidence=0.9,
            handoff_needed=True, handoff_code="contact_request", handoff_reason="고객이 상담사 연결을 요청함",
        )
    return ChatResponse(
        answer=f"[MOCK] '{msg}' 에 대한 가짜 답변입니다. 실제 모델이 연결되면 근거 기반 답변으로 바뀝니다.",
        category="은행", topic="대출문의(만기/연장/조회등)", confidence=0.91,
        sources=[Source(doc_id="mock-001", category="은행", topic="대출문의(만기/연장/조회등)",
                        score=0.91, snippet="(mock) 대출 만기 연장 안내...")],
    )
