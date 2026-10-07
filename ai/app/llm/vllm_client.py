"""HTTP client for the vLLM OpenAI-compatible server (defined in docker-compose.server.yml)."""
from typing import List, Optional

import httpx

from app.core import config
from app.llm.prompts import INSTRUCTION

ADAPTER_NAMES = {
    "은행": "bank",
    "보험": "insurance",
    "증권": "stock",
}


def _format_doc(doc: dict) -> str:
    """One reference document as "고객질문:...\n상담사답변:..." (a missing field is skipped)."""
    lines = []
    if doc.get("question"):
        lines.append(f"고객질문:{doc['question']}")
    if doc.get("answer"):
        lines.append(f"상담사답변:{doc['answer']}")
    return "\n".join(lines)


def build_question(message: str, docs: Optional[List[dict]] = None, history: Optional[List[dict]] = None) -> str:
    """Build the single user message the adapters were trained on.

    Args:
        message: Current customer question.
        docs: Retrieved documents (dicts with "question" and "answer"); order is kept. Only these two fields reach the LLM;
            counselor-only fields (follow_up_question, output) are for the counselor screen, not for the prompt.
        history: Earlier turns as [{"role": "user"|"assistant", "content": "..."}], oldest first.

    Returns:
        "[이전 대화 ...] 고객 질문 : ... RAG 결과: ..." text for generate_answer.
    """
    rag = "\n\n".join(text for text in map(_format_doc, docs or []) if text)
    past = "".join(f"{'고객' if turn['role'] == 'user' else '상담사'}: {turn['content']}\n" for turn in history or [])
    prefix = f"이전 대화:\n{past}\n" if past else ""
    return f"{prefix}고객 질문 : {message}\nRAG 결과: {rag}"


def generate_answer(
    category: str,
    question: str,
    max_tokens: int = 512,
    client: Optional[httpx.Client] = None,
) -> str:
    """Generate an answer with the category's LoRA adapter served by vLLM.

    Args:
        category: Finance domain; one of ADAPTER_NAMES keys (selects the adapter).
        question: Customer question, sent as the user message.
        max_tokens: Maximum number of tokens to generate.
        client: Optional HTTP client, mainly to inject a mock transport in tests.

    Returns:
        The generated answer text, stripped.

    Raises:
        ValueError: If category, question, or max_tokens is invalid.
        httpx.HTTPError: If the request fails or vLLM returns a non-2xx status.
        RuntimeError: If the response body has no completion text.
    """
    if category not in ADAPTER_NAMES:
        raise ValueError(f"지원하지 않는 분야입니다: {category}. 사용 가능: {list(ADAPTER_NAMES)}")

    if not isinstance(question, str) or not question.strip():
        raise ValueError("질문은 비어 있지 않은 문자열이어야 합니다.")

    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError("max_tokens는 양의 정수여야 합니다.")

    payload = {
        "model": ADAPTER_NAMES[category],
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": question},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "repetition_penalty": 1.05,
    }
    url = f"{config.VLLM_BASE_URL.rstrip('/')}/chat/completions"

    if client is None:
        with httpx.Client(timeout=config.VLLM_TIMEOUT) as owned_client:
            response = owned_client.post(url, json=payload)
    else:
        response = client.post(url, json=payload)
    response.raise_for_status()

    response_body = response.json()
    try:
        return response_body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError(f"vLLM 응답 형식이 올바르지 않습니다: {response_body}") from error
