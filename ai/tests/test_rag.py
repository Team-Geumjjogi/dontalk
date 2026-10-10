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


QA_ROW = {
    "qa_id": "21-1_bk_01", "question": "이체 방법?", "answer": "앱에서 가능",
    "follow_up_question": "한도는?", "output": "종합 답변", "consulting_category": "은행", "consulting_topic": "이체", "distance": 0.25,
}
CRAWLING_ROW = {
    "id": 7, "question": "통장 만들기가 뭔가요?", "answer": "앱에서 개설합니다",
    "consulting_category": "은행", "consulting_topic": "전자금융", "distance": 0.1,
}


def test_qa_row_keeps_db_values_in_common_format():
    doc = retriever._to_doc(retriever.SPEC_QA, QA_ROW)
    assert doc["doc_id"] == "21-1_bk_01" and doc["source"] == "qa"
    assert doc["question"] == "이체 방법?" and doc["answer"] == "앱에서 가능"  # LLM 에 줄 질의 + 답변
    assert doc["follow_up_question"] == "한도는?" and doc["output"] == "종합 답변"
    assert doc["similarity"] == 0.75 and "distance" not in doc


def test_crawling_row_gets_prefixed_id_and_empty_counselor_fields():
    doc = retriever._to_doc(retriever.SPEC_CRAWLING, CRAWLING_ROW)
    assert doc["doc_id"] == "crawling-7" and doc["source"] == "crawling"
    assert doc["question"] == "통장 만들기가 뭔가요?" and doc["answer"] == "앱에서 개설합니다"
    assert doc["follow_up_question"] is None and doc["output"] is None
    assert doc["similarity"] == 0.9


def test_both_tables_return_the_same_keys():
    qa, crawling = retriever._to_doc(retriever.SPEC_QA, QA_ROW), retriever._to_doc(retriever.SPEC_CRAWLING, CRAWLING_ROW)
    assert set(qa) == set(crawling)


def test_select_columns_exist_in_each_table_design():
    # 크롤링 테이블에는 이 컬럼들이 없다. SELECT 에 넣으면 "column does not exist" 오류가 난다.
    assert not {"qa_id", "follow_up_question", "output"} & set(retriever.SPEC_CRAWLING.columns)
    assert {"id", "question", "answer"} <= set(retriever.SPEC_CRAWLING.columns)
    # LLM 에는 질의 + 답변만 주므로 full_source(5줄 통째)는 어느 테이블에서도 가져오지 않는다
    assert "full_source" not in retriever.SPEC_QA.columns + retriever.SPEC_CRAWLING.columns


def test_search_merges_both_tables_sorted_by_similarity(monkeypatch):
    class FakeModel:
        def encode(self, text, **kwargs):
            assert kwargs["prompt_name"] == "query"
            return [0.0]

    rows_by_table = {retriever.SPEC_QA.table: [QA_ROW], retriever.SPEC_CRAWLING.table: [CRAWLING_ROW]}

    def fake_query(statement, params):
        # 어느 테이블을 조회하는 SQL 인지 문장에 들어 있는 테이블명으로 구분한다
        text = statement.as_string(None)
        return next(rows for table, rows in rows_by_table.items() if f'"{table}"' in text)

    monkeypatch.setattr(retriever, "_get_model", lambda: FakeModel())
    monkeypatch.setattr(retriever, "_query", fake_query)
    docs = retriever.search("질문")
    assert [d["doc_id"] for d in docs] == ["crawling-7", "21-1_bk_01"]  # 유사도 0.9, 0.75 순


def test_search_keeps_only_top_k_by_similarity_across_both_tables(monkeypatch):
    monkeypatch.setattr(retriever, "_embed_query", lambda q: [0.0])
    monkeypatch.setattr(retriever, "TOP_K", 5)

    def five_each(spec, vec, top_k=None):
        base = {"qa": 0.80, "crawling": 0.79}[spec.source]  # qa 0.80,0.78,.. / 크롤링 0.79,0.77,..
        return [
            {**retriever._to_doc(spec, {**(QA_ROW if spec.source == "qa" else CRAWLING_ROW), "distance": 1 - (base - 0.02 * i)}),
             "doc_id": f"{spec.source}-{i}"}
            for i in range(5)
        ]

    monkeypatch.setattr(retriever, "_search_table", five_each)
    docs = retriever.search("질문")
    assert len(docs) == 5  # 5+5 건 중 상위 5건만
    sims = [d["similarity"] for d in docs]
    assert sims == sorted(sims, reverse=True) and round(sims[0], 2) == 0.80
    assert [d["doc_id"] for d in docs] == ["qa-0", "crawling-0", "qa-1", "crawling-1", "qa-2"]  # 두 테이블이 섞여 유사도순


def test_search_skips_a_failing_table_but_raises_when_all_fail(monkeypatch):
    monkeypatch.setattr(retriever, "_embed_query", lambda q: [0.0])

    def only_qa_works(spec, vec, top_k=None):
        if spec is retriever.SPEC_CRAWLING:
            raise RuntimeError("crawling down")
        return [retriever._to_doc(spec, QA_ROW)]

    monkeypatch.setattr(retriever, "_search_table", only_qa_works)
    assert [d["doc_id"] for d in retriever.search("질문")] == ["21-1_bk_01"]

    def all_down(spec, vec, top_k=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(retriever, "_search_table", all_down)
    with pytest.raises(RuntimeError):
        retriever.search("질문")


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
