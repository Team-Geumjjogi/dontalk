import pytest

from app.core import config
from app.schemas.chat import ChatRequest
from app.services import chat_service as cs


def _doc(sim, cat="은행", topic="대출문의", question="만기 연장?"):
    return {"qa_id": "q1", "similarity": sim, "consulting_category": cat, "consulting_topic": topic,
            "question": question, "answer": "앱에서 가능", "output": "종합 ●●원", "full_source": "전체 ●●"}


@pytest.fixture
def real_mode(monkeypatch):
    """mock 이 아닌 실제 흐름. 검색/LLM 은 테스트에서 바꿔 끼운다."""
    monkeypatch.setattr(config, "AI_MOCK_MODE", False)
    calls = []
    monkeypatch.setattr(cs, "_generate", lambda m, c, d: calls.append((m, c, d)) or "답변입니다")
    return calls


def ask(message="대출 만기 연장 어떻게 해요?"):
    return cs.answer(ChatRequest(session_id="s", message=message))


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

    def boom(m, c, d):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(cs, "_generate", boom)
    r = ask()
    assert r.handoff_needed and "LLM 오류" in r.handoff_reason


def test_mask():
    assert cs._mask("추가 보험료는 ●●원") == "추가 보험료는 [비공개]원"
    assert cs._mask_doc({"output": "●●일", "similarity": 0.5}) == {"output": "[비공개]일", "similarity": 0.5}
