"""HTTP client for the vLLM OpenAI-compatible server (defined in docker-compose.server.yml)."""
from typing import Optional

import httpx

from app.core import config
from app.llm.prompts import INSTRUCTION

ADAPTER_NAMES = {
    "은행": "bank",
    "보험": "insurance",
    "증권": "securities",
}

REQUEST_TIMEOUT_SECONDS = 120.0


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
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as owned_client:
            response = owned_client.post(url, json=payload)
    else:
        response = client.post(url, json=payload)
    response.raise_for_status()

    response_body = response.json()
    try:
        return response_body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError(f"vLLM 응답 형식이 올바르지 않습니다: {response_body}") from error
