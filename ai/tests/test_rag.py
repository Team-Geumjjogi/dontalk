import threading
import time

import pytest

from app.rag import retriever, router


def _doc(cat, topic):
    return {"consulting_category": cat, "consulting_topic": topic}


def test_decide_majority_and_confidence():
    docs = [_doc("은행", "대출"), _doc("은행", "대출"), _doc("보험", "청구"), _doc("은행", "예금"), _doc("은행", "대출")]
    assert router.decide(docs) == ("은행", "대출", 0.8)


def test_decide_tie_prefers_higher_rank():
    docs = [_doc("증권", "주식"), _doc("은행", "대출"), _doc("은행", "예금"), _doc("증권", "펀드")]
    category, topic, confidence = router.decide(docs)
    assert (category, topic, confidence) == ("증권", "주식", 0.5)


def test_decide_empty():
    assert router.decide([]) == (None, None, 0.0)


def test_search_blank_query_returns_empty():
    assert retriever.search("   ") == []


def test_search_converts_distance_to_similarity(monkeypatch):
    class FakeModel:
        def encode(self, text, **kwargs):
            assert kwargs["prompt_name"] == "query"
            return [0.0]

    monkeypatch.setattr(retriever, "_get_model", lambda: FakeModel())
    monkeypatch.setattr(retriever, "_query", lambda statement, params: [{"qa_id": "a", "distance": 0.25}])
    rows = retriever.search("질문")
    assert rows[0]["similarity"] == 0.75 and "distance" not in rows[0]


# --- 공용 DB 연결이 조용히 끊겼을 때: 멈추지 말고 연결을 버리고 재시도 ---
class FakeConn:
    closed = False

    def __init__(self, hangs):
        self.hangs = hangs

    def close(self):
        self.closed = True


def _use_connections(monkeypatch, *connections):
    pending = list(connections)
    monkeypatch.setattr(retriever, "_conn", None)
    monkeypatch.setattr(retriever, "QUERY_TIMEOUT", 0.2)
    monkeypatch.setattr(retriever, "_connect", lambda: pending.pop(0))

    def fake_run(conn, statement, params):
        if conn.hangs:
            threading.Event().wait(1.5)  # 응답 없는 연결 흉내
        return [{"ok": 1}]

    monkeypatch.setattr(retriever, "_run", fake_run)


def test_hanging_connection_is_dropped_and_query_retried(monkeypatch):
    stuck, healthy = FakeConn(hangs=True), FakeConn(hangs=False)
    _use_connections(monkeypatch, stuck, healthy)
    started = time.perf_counter()
    assert retriever._query("SELECT 1", None) == [{"ok": 1}]
    assert time.perf_counter() - started < 1.0          # 멈춰 있지 않고 타임아웃 뒤 바로 새 연결로 성공
    assert retriever._conn is healthy


def test_query_gives_up_with_error_when_every_connection_hangs(monkeypatch):
    _use_connections(monkeypatch, FakeConn(hangs=True), FakeConn(hangs=True))
    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        retriever._query("SELECT 1", None)
    assert time.perf_counter() - started < 1.0 and retriever._conn is None
