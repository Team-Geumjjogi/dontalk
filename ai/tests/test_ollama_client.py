import httpx
import pytest

from app.llm import ollama_client


def test_build_messages_without_docs():
    msgs = ollama_client.build_messages("대출 연장이요")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "대출 연장이요" in msgs[1]["content"]
    assert "참고 정보" not in msgs[1]["content"]


def test_build_messages_with_docs():
    docs = [{"question": "만기 연장?", "answer": "앱에서 가능", "output": "종합", "follow_up_question": "쓰지 않음"}]
    user = ollama_client.build_messages("연장 문의", docs)[1]["content"]
    assert "[참고 1]" in user and "고객 질문: 만기 연장?" in user and "종합 답변: 종합" in user
    assert "쓰지 않음" not in user


def test_generate_ok(monkeypatch):
    fake = httpx.Response(200, json={"message": {"content": " 안녕하세요 "}}, request=httpx.Request("POST", "http://x"))
    monkeypatch.setattr(ollama_client.httpx, "post", lambda *a, **k: fake)
    assert ollama_client.generate("hi") == "안녕하세요"


def test_generate_connection_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(ollama_client.httpx, "post", boom)
    with pytest.raises(ollama_client.OllamaError):
        ollama_client.generate("hi")


def test_build_messages_with_history_keeps_order():
    history = [{"role": "user", "content": "이전 질문"}, {"role": "assistant", "content": "이전 답변"}]
    msgs = ollama_client.build_messages("그럼 수수료는요?", [{"question": "q"}], history)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "이전 질문" and "그럼 수수료는요?" in msgs[-1]["content"]
    assert "참고 정보" in msgs[-1]["content"] and "참고 정보" not in msgs[1]["content"]
