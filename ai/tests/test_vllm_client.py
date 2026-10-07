import json

import httpx
import pytest

from app.core import config
from app.llm import vllm_client
from app.llm.prompts import INSTRUCTION


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def test_request_shape_and_adapter_selection(monkeypatch):
    monkeypatch.setattr(config, "VLLM_BASE_URL", "http://vllm:8000/v1/")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion("  안내드립니다.  "))

    answer = vllm_client.generate_answer("보험", "청구 방법이 궁금해요", client=make_client(handler))

    assert answer == "안내드립니다."
    assert captured["url"] == "http://vllm:8000/v1/chat/completions"
    body = captured["body"]
    assert body["model"] == "insurance"
    assert body["messages"] == [
        {"role": "system", "content": INSTRUCTION},
        {"role": "user", "content": "청구 방법이 궁금해요"},
    ]
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.0


@pytest.mark.parametrize("category, adapter", [("은행", "bank"), ("보험", "insurance"), ("증권", "stock")])
def test_all_categories_map_to_adapters(category, adapter):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(200, json=completion("ok"))

    vllm_client.generate_answer(category, "질문", client=make_client(handler))
    assert seen == [adapter]


@pytest.mark.parametrize(
    "category, question, max_tokens",
    [("부동산", "질문", 512), ("은행", "   ", 512), ("은행", None, 512), ("은행", "질문", 0), ("은행", "질문", True)],
)
def test_invalid_input_is_rejected_before_request(category, question, max_tokens):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent")

    with pytest.raises(ValueError):
        vllm_client.generate_answer(category, question, max_tokens, client=make_client(handler))


def test_build_question_format():
    docs = [{"question": "질문1", "answer": "답변1"}, {"question": "질문2", "answer": "답변2"}, {}]  # 빈 문서는 건너뛴다

    question = vllm_client.build_question("수수료는요?", docs)

    assert question == "고객 질문 : 수수료는요?\nRAG 결과: 고객질문:질문1\n상담사답변:답변1\n\n고객질문:질문2\n상담사답변:답변2"


def test_build_question_has_no_conversation_history_parameter():
    import inspect

    assert "history" not in inspect.signature(vllm_client.build_question).parameters  # 이전 대화는 프롬프트에 넣지 않는다


def test_build_question_gives_llm_only_question_and_answer():
    doc = {"question": "Q", "answer": "A", "follow_up_question": "예상 꼬리질문", "output": "예상 종합답변", "full_source": "통째 5줄",
           "similarity": 0.9, "doc_id": "q1"}
    question = vllm_client.build_question("질문", [doc])
    assert question.endswith("RAG 결과: 고객질문:Q\n상담사답변:A")
    assert not any(hidden in question for hidden in ("예상 꼬리질문", "예상 종합답변", "통째 5줄", "0.9", "q1"))  # 상담사용 값은 프롬프트에 없다


def test_build_question_without_docs_or_history():
    assert vllm_client.build_question("질문") == "고객 질문 : 질문\nRAG 결과: "


def test_client_uses_configured_timeout(monkeypatch):
    monkeypatch.setattr(config, "VLLM_TIMEOUT", 12.0)
    seen = {}

    class FakeClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            super().__init__(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=completion("ok"))))

    monkeypatch.setattr(vllm_client.httpx, "Client", FakeClient)
    assert vllm_client.generate_answer("은행", "질문") == "ok"
    assert seen["timeout"] == 12.0


def test_http_error_status_is_raised():
    client = make_client(lambda request: httpx.Response(503, json={"error": "loading"}))
    with pytest.raises(httpx.HTTPStatusError):
        vllm_client.generate_answer("은행", "질문", client=client)


@pytest.mark.parametrize("response_body", [{}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_malformed_response_raises_runtime_error(response_body):
    client = make_client(lambda request: httpx.Response(200, json=response_body))
    with pytest.raises(RuntimeError):
        vllm_client.generate_answer("은행", "질문", client=client)


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("timed out")])
def test_connection_errors_propagate(error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(httpx.HTTPError):
        vllm_client.generate_answer("은행", "질문", client=make_client(handler))
