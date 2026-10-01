import pytest

from app.core import config
from app.schemas.chat import ChatRequest, ChatTurn
from app.services import chat_service as cs


def _doc(sim, cat="은행", topic="대출문의", question="만기 연장?"):
    return {"qa_id": "q1", "similarity": sim, "consulting_category": cat, "consulting_topic": topic,
            "question": question, "answer": "앱에서 가능", "output": "종합 ●●원", "full_source": "전체 ●●"}


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


@pytest.mark.parametrize("msg", ["그 아이디 삭제 좀 부탁드릴게요", "계좌 해지해 주세요", "이체 한도 올려주세요"])
def test_action_request_hands_off_without_llm(real_mode, monkeypatch, msg):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    r = ask(msg)
    assert r.handoff_needed and "실제 처리" in r.handoff_reason and real_mode == []
    assert r.category == "은행"  # 상담사 대기큐 분류용으로 분야는 유지


@pytest.mark.parametrize("msg", ["계좌 해지 방법이 궁금해요", "해지 절차 알려주세요", "이체 한도는 얼마인가요?"])
def test_info_question_is_not_action(msg):
    assert not cs.is_action_request(msg)


def test_contact_request(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)
    r = ask("상담사 연결해 주세요")
    assert r.handoff_needed and "상담사 연결" in r.handoff_reason and real_mode == []


def test_low_similarity_hands_off_and_drops_category(real_mode, monkeypatch):
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.41)] * 5)
    r = ask("오늘 날씨 어때요?")
    assert r.handoff_needed and r.category is None and r.confidence == 0.0 and r.sources == [] and real_mode == []


def test_low_confidence_hands_off_but_keeps_guess(real_mode, monkeypatch):
    docs = [_doc(0.8, "은행"), _doc(0.78, "보험"), _doc(0.75, "증권"), _doc(0.7, "보험"), _doc(0.7, "증권")]
    monkeypatch.setattr(cs, "_search", lambda m: docs)
    r = ask()
    assert r.handoff_needed and "확신도" in r.handoff_reason and r.category is not None and real_mode == []


def test_search_error_hands_off(real_mode, monkeypatch):
    def boom(m):
        raise ConnectionError("db down")
    monkeypatch.setattr(cs, "_search", boom)
    r = ask()
    assert r.handoff_needed and "검색 오류" in r.handoff_reason


def test_llm_error_hands_off(monkeypatch):
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    monkeypatch.setattr(cs, "_search", lambda m: [_doc(0.8)] * 5)

    def boom(m, c, d, h):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(cs, "_generate", boom)
    r = ask()
    assert r.handoff_needed and "LLM 오류" in r.handoff_reason


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
