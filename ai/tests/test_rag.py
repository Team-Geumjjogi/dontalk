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
