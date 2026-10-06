import pytest

from app.core import config
from app.schemas.chat import ChatRequest, ChatTurn
from app.services import chat_service as cs


def _doc(sim, cat="은행", topic="대출문의", question="만기 연장?"):
    return {"doc_id": "q1", "similarity": sim, "consulting_category": cat, "consulting_topic": topic,
            "question": question, "answer": "앱에서 가능", "output": "종합 ●●원", "full_source": "전체 ●●",
            "follow_up_question": "추가로 필요한 서류는?"}


@pytest.fixture
def real_mode(monkeypatch):
    """mock 이 아닌 실제 흐름. 검색/LLM 은 테스트에서 바꿔 끼운다."""
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    calls = []
    monkeypatch.setattr(cs, "_generate", lambda m, c, d, h: calls.append((m, c, d, h)) or "답변입니다")
    return calls


def ask(message="대출 만기 연장 어떻게 해요?", history=()):
    return cs.answer(ChatRequest(session_id="s", message=message, history=[ChatTurn(**t) for t in history]))


def test_normal_answer(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    r = ask()
    assert not r.handoff_needed and r.answer == "답변입니다"
    assert (r.category, r.topic, r.confidence) == ("은행", "대출문의", 1.0)
    assert r.sources[0].doc_id == "q1" and len(real_mode) == 1
    assert r.sources[0].follow_up_question == "추가로 필요한 서류는?" and r.sources[0].output == "종합 ●●원"


@pytest.mark.parametrize("msg", ["그 아이디 삭제 좀 부탁드릴게요", "계좌 해지해 주세요", "이체 한도 올려주세요"])
def test_action_request_hands_off_without_llm(real_mode, monkeypatch, msg):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    r = ask(msg)
    assert r.handoff_needed and r.handoff_code == "action_request" and real_mode == []
    assert r.category == "은행"  # 상담사 대기큐 분류용으로 분야는 유지


@pytest.mark.parametrize("msg", ["계좌 해지 방법이 궁금해요", "해지 절차 알려주세요", "이체 한도는 얼마인가요?"])
def test_info_question_is_not_action(msg):
    assert not cs.is_action_request(msg)


def test_contact_request(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    r = ask("상담사 연결해 주세요")
    assert r.handoff_needed and r.handoff_code == "contact_request" and real_mode == []


def test_out_of_scope_gets_guidance_without_handoff(real_mode, monkeypatch):
    """날씨/잡담처럼 금융과 무관한 질문(유사도가 매우 낮음)은 상담사에게 넘기지 않고 안내만 한다."""
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.41)] * 5)
    r = ask("오늘 날씨 어때요?")
    assert not r.handoff_needed and r.answer == cs.MSG_OUT_OF_SCOPE and "상담사 연결" in r.answer
    assert r.category is None and r.sources == [] and real_mode == []


def test_weak_basis_hands_off_and_drops_category(real_mode, monkeypatch):
    """금융과 관련은 있어 보이지만 근거가 약한 질문(0.45~0.55)은 상담사에게 넘긴다."""
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.50)] * 5)
    r = ask("HTS 에서 피보나치 도구는 어디 있나요?")
    assert r.handoff_needed and r.handoff_code == "no_basis" and r.category is None and r.confidence == 0.0
    assert r.sources == [] and real_mode == []


def test_low_confidence_hands_off_but_keeps_guess(real_mode, monkeypatch):
    docs = [_doc(0.8, "은행"), _doc(0.78, "보험"), _doc(0.75, "증권"), _doc(0.7, "보험"), _doc(0.7, "증권")]
    monkeypatch.setattr(cs, "_search", lambda m: docs)
    r = ask()
    assert r.handoff_needed and r.handoff_code == "low_confidence" and r.category is not None and real_mode == []


def test_search_error_hands_off(real_mode, monkeypatch):
    def boom(m):
        raise ConnectionError("db down")
    monkeypatch.setattr(cs, "_search", boom)
    r = ask()
    assert r.handoff_needed and r.handoff_code == "ai_error" and "검색 오류" in r.handoff_reason


def test_llm_error_hands_off(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)

    def boom(m, c, d, h):
        raise RuntimeError("vllm down")
    monkeypatch.setattr(cs, "_generate", boom)
    r = ask()
    assert r.handoff_needed and r.handoff_code == "ai_error" and "LLM 오류" in r.handoff_reason


def test_mask():
    assert cs._mask("추가 보험료는 ●●원") == "추가 보험료는 [비공개]원"
    assert cs._mask_doc({"output": "●●일", "similarity": 0.5}) == {"output": "[비공개]일", "similarity": 0.5}


# --- 후처리 / 인사 / 다중턴 ---
def test_clean_answer_strips_markdown():
    text = "### 안내\n1. **본인 확인**을 합니다.\n2. `앱`에서 신청합니다."
    assert cs.clean_answer(text) == "안내\n1. 본인 확인을 합니다.\n2. 앱에서 신청합니다."


def test_clean_answer_replaces_redacted_sentences_once():
    text = "진단금은 [비공개]원입니다. 입원비는 하루 [비공개]원입니다. 자세한 건 문의하세요."
    cleaned = cs.clean_answer(text)
    assert "[비공개]" not in cleaned
    assert cleaned.count(cs.MSG_REDACTED) == 1 and cleaned.endswith("자세한 건 문의하세요.")


@pytest.mark.parametrize("msg,expected", [("안녕하세요", cs.MSG_GREETING), ("안녕하세요!", cs.MSG_GREETING),
                                          ("감사합니다 ~", cs.MSG_THANKS), ("안녕하세요 대출 연장이요", None)])
def test_small_talk(msg, expected):
    assert cs.small_talk_reply(msg) == expected


def test_greeting_skips_search_and_llm(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda q: pytest.fail("검색하면 안 됨"))
    r = ask("안녕하세요")
    assert not r.handoff_needed and r.answer == cs.MSG_GREETING and real_mode == []


def test_answer_is_cleaned(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda q: [_doc(0.8)] * 5)
    monkeypatch.setattr(cs, "_generate", lambda m, c, d, h: "**안내**드립니다. 금액은 [비공개]원입니다.")
    assert ask().answer == "안내드립니다. " + cs.MSG_REDACTED


HIST = [{"role": "user", "content": "대출 만기 연장하고 싶어요"}, {"role": "assistant", "content": "앱에서 가능합니다."}]


def test_search_query_for_follow_up():
    h = [{"role": "user", "content": "대출 만기 연장하고 싶어요"}, {"role": "assistant", "content": "앱에서 가능합니다."}]
    assert cs.build_search_query("그럼 수수료는요?", h) == "대출 만기 연장하고 싶어요 그럼 수수료는요?"
    assert cs.build_search_query("그러면 그 경우에 필요한 서류는 무엇이 있나요", h).startswith("대출 만기 연장하고 싶어요 ")


def test_search_query_for_new_topic_or_no_history():
    h = [{"role": "user", "content": "대출 만기 연장하고 싶어요"}]
    long_q = "실손보험 청구하려면 어떤 서류가 필요한가요?"
    assert cs.build_search_query(long_q, h) == long_q
    assert cs.build_search_query("수수료는요?", []) == "수수료는요?"


def test_follow_up_uses_history_for_search_and_llm(real_mode, monkeypatch):
    queries = []
    monkeypatch.setattr(cs, "_search", lambda q: queries.append(q) or [_doc(0.8)] * 5)
    ask("그럼 수수료는요?", history=HIST)
    assert queries == ["대출 만기 연장하고 싶어요 그럼 수수료는요?"]
    _, _, _, passed_history = real_mode[0]
    assert passed_history == HIST


def test_history_is_trimmed(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda q: [_doc(0.8)] * 5)
    many = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"발화{i} " + "가" * 800} for i in range(10)]
    ask("수수료는요?", history=many)
    passed = real_mode[0][3]
    assert len(passed) == cs.MAX_HISTORY_TURNS and all(len(t["content"]) <= cs.MAX_TURN_CHARS for t in passed)
    assert passed[-1]["content"].startswith("발화9")


# --- 답변 길이 제한 ---
def test_limit_answer_keeps_short_answers_untouched():
    assert cs.limit_answer("짧은 답변입니다.", 100) == "짧은 답변입니다."


def test_limit_answer_cuts_at_sentence_boundary_and_adds_note():
    text = "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다. 네 번째 문장입니다."
    limited = cs.limit_answer(text, 30)
    assert limited == "첫 번째 문장입니다. 두 번째 문장입니다.\n" + cs.MSG_TRUNCATED   # 문장 중간에서 끊기지 않는다


def test_limit_answer_keeps_line_breaks_and_stops_at_budget():
    text = "1. 서류를 준비합니다.\n2. 앱에서 신청합니다.\n3. 심사 결과를 기다립니다.\n4. 문자로 안내받습니다."
    limited = cs.limit_answer(text, 30)
    assert limited.startswith("1. 서류를 준비합니다.\n2. 앱에서 신청합니다.") and "3." not in limited and limited.endswith(cs.MSG_TRUNCATED)


def test_limit_answer_hard_cuts_a_single_endless_sentence():
    limited = cs.limit_answer("가" * 200, 50)
    assert limited.startswith("가" * 50 + "…") and limited.endswith(cs.MSG_TRUNCATED)


def test_long_llm_answer_is_limited_in_response(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda q: [_doc(0.8)] * 5)
    monkeypatch.setattr(cs, "_generate", lambda m, c, d, h: "안내 문장입니다. " * 100)
    answer = ask().answer
    assert len(answer) <= cs.ANSWER_MAX_CHARS + len(cs.MSG_TRUNCATED) + 2 and answer.endswith(cs.MSG_TRUNCATED)


# --- 상담사 연결/처리 요청 규칙 ---
@pytest.mark.parametrize("msg", ["상담사 연결해 주세요", "상담원이랑 통화하고 싶어요", "직원 바꿔주세요", "사람이랑 얘기하고 싶어요", "담당자와 전화 연결 부탁드립니다"])
def test_contact_requests_detected(msg):
    assert cs.is_contact_request(msg)


@pytest.mark.parametrize("msg", ["직원이 친절했어요", "보험 가입 조건이 궁금합니다", "사람들이 많이 가입하나요"])
def test_non_contact_messages_not_detected(msg):
    assert not cs.is_contact_request(msg)


@pytest.mark.parametrize("msg", ["500만원 송금해 주세요", "자동이체 취소해주세요", "비밀번호 변경해 주세요", "카드 재발급 부탁드려요"])
def test_more_action_requests_detected(msg):
    assert cs.is_action_request(msg)


@pytest.mark.parametrize("msg", ["해지하면 수수료가 있나요", "계좌를 해지하고 싶어요", "카드 재발급 절차를 설명해 주세요"])
def test_more_info_questions_not_action(msg):
    assert not cs.is_action_request(msg)


def test_answer_logs_timings(real_mode, monkeypatch, caplog):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    with caplog.at_level("INFO", logger="app.chat"):
        ask()
    assert any("chat 답변" in r.message and "검색" in r.message and "LLM" in r.message for r in caplog.records)


# --- 후속 질문 검색: 직전 질문과 무관한 짧은 업무 밖 질문은 합치지 않는다 ---
def _record_searches(monkeypatch, similarity_by_query):
    queries = []

    def fake_search(q):
        queries.append(q)
        return [_doc(similarity_by_query(q))] * 5

    monkeypatch.setattr(cs, "_search", fake_search)
    return queries


PREV = [{"role": "user", "content": "대출 만기 연장하고 싶어요"}, {"role": "assistant", "content": "앱에서 가능해요."}]


def test_find_docs_without_history_searches_once(monkeypatch):
    queries = _record_searches(monkeypatch, lambda q: 0.8)
    cs.find_docs("수수료는요?", [])
    assert queries == ["수수료는요?"]


def test_find_docs_with_referent_always_glues_without_extra_search(monkeypatch):
    queries = _record_searches(monkeypatch, lambda q: 0.3 if q == "그럼 수수료는요?" else 0.85)
    docs = cs.find_docs("그럼 수수료는요?", PREV)
    assert queries == ["대출 만기 연장하고 싶어요 그럼 수수료는요?"] and docs[0]["similarity"] == 0.85


def test_find_docs_short_real_follow_up_is_glued_when_standalone_is_financial(monkeypatch):
    queries = _record_searches(monkeypatch, lambda q: 0.65 if q == "수수료는요?" else 0.85)
    docs = cs.find_docs("수수료는요?", PREV)
    assert queries == ["수수료는요?", "대출 만기 연장하고 싶어요 수수료는요?"] and docs[0]["similarity"] == 0.85


def test_find_docs_short_off_topic_message_is_not_glued(monkeypatch):
    queries = _record_searches(monkeypatch, lambda q: 0.41 if q == "오늘 날씨 어때요?" else 0.80)
    docs = cs.find_docs("오늘 날씨 어때요?", PREV)
    assert queries == ["오늘 날씨 어때요?"] and docs[0]["similarity"] == 0.41     # 단독 결과가 그대로 쓰여 업무 밖으로 판정된다


def test_off_topic_after_finance_question_gets_guidance(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    _record_searches(monkeypatch, lambda q: 0.41 if q == "오늘 날씨 어때요?" else 0.80)
    monkeypatch.setattr(cs, "_generate", lambda *a: pytest.fail("LLM 을 부르면 안 됨"))
    r = ask("오늘 날씨 어때요?", history=HIST)
    assert not r.handoff_needed and r.answer == cs.MSG_OUT_OF_SCOPE and r.category is None


def test_generate_sends_masked_docs_to_vllm(monkeypatch):
    sent = {}

    def fake_generate_answer(category, question, **kwargs):
        sent.update(category=category, question=question)
        return "답변"

    monkeypatch.setattr(cs.vllm_client, "generate_answer", fake_generate_answer)

    assert cs._generate("질문", "은행", [{"full_source": "계좌 ●●●● 입니다"}], []) == "답변"
    assert sent["category"] == "은행"
    assert "●" not in sent["question"] and "[비공개]" in sent["question"]


def test_warm_up_calls_retriever_warm_up(monkeypatch):
    from app.rag import retriever

    calls = []
    monkeypatch.setattr(retriever, "warm_up", lambda: calls.append("warm"))
    cs.warm_up()
    assert calls == ["warm"]


def test_warm_up_swallows_errors(monkeypatch):
    from app.rag import retriever

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(retriever, "warm_up", boom)
    cs.warm_up()  # must not raise: the server should still start


def test_app_startup_runs_warm_up_unless_mock(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []
    monkeypatch.setattr(cs, "warm_up", lambda: calls.append("warm"))

    monkeypatch.setattr(config, "AI_MOCK_MODE", True)
    with TestClient(app):
        pass
    assert calls == []

    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    with TestClient(app):
        pass
    assert calls == ["warm"]


def test_multi_turn_history_reaches_vllm_question(monkeypatch):
    sent = {}

    def fake_generate_answer(category, question, **kwargs):
        sent.update(category=category, question=question)
        return "수수료는 없습니다."

    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    monkeypatch.setattr(cs.vllm_client, "generate_answer", fake_generate_answer)

    r = ask("그럼 수수료는요?", history=HIST)

    assert not r.handoff_needed and r.answer == "수수료는 없습니다."
    question = sent["question"]
    assert question.index("고객: 대출 만기 연장하고 싶어요") < question.index("상담사: 앱에서 가능합니다.") < question.index("고객 질문 : 그럼 수수료는요?")
    assert sent["category"] == "은행"


def test_llm_error_reason_has_message_but_answer_does_not(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)

    def boom(m, c, d, h):
        raise RuntimeError("connect to http://vllm:8000/v1\nrefused")
    monkeypatch.setattr(cs, "_generate", boom)

    r = ask()
    assert r.handoff_reason == "LLM 오류: RuntimeError: connect to http://vllm:8000/v1 refused"
    assert "vllm" not in r.answer and r.answer == cs.MSG_ERROR


def test_search_error_reason_has_message(real_mode, monkeypatch):
    def boom(m):
        raise ConnectionError("db down")
    monkeypatch.setattr(cs, "_search", boom)
    assert ask().handoff_reason == "검색 오류: ConnectionError: db down"


def test_error_reason_is_truncated_and_handles_empty_message():
    long_reason = cs._error_reason("LLM 오류", RuntimeError("x" * 1000))
    assert long_reason == "LLM 오류: RuntimeError: " + "x" * cs.ERROR_DETAIL_MAX
    assert cs._error_reason("LLM 오류", RuntimeError()) == "LLM 오류: RuntimeError"
