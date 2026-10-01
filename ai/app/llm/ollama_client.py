"""Ollama(base 모델) 호출. 로컬 개발/웹 연동용.

model.py(HF transformers + 분야별 LoRA)와는 독립된 모듈이라 서로 영향을 주지 않습니다.
설정은 .env 에서 읽으며, 안 적어도 기본값(로컬 Ollama + exaone3.5:2.4b)으로 동작합니다.
  OLLAMA_HOST        기본 http://localhost:11434  (서버로 옮길 때 이 주소만 변경)
  OLLAMA_MODEL       기본 exaone3.5:2.4b
  OLLAMA_TIMEOUT     기본 50초 (web/ai_client 의 60초보다 짧게)
  LLM_TEMPERATURE / LLM_MAX_TOKENS / LLM_NUM_CTX
"""
import os
from typing import List, Optional

import httpx
from dotenv import load_dotenv

from app.llm.prompts import INSTRUCTION

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "exaone3.5:2.4b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "50"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "8192"))  # Ollama 기본 4096 은 RAG 문서 여러 개면 모자람

# base 모델은 답변이 길고 마크다운을 쓰는 경향이 있어서 채팅 UI에 맞게 형식을 제한한다.
_STYLE = (
    " 답변은 한국어 평문 3~5문장으로 간결하게 쓰고, 마크다운(제목·굵게·목록)은 사용하지 마세요."
    " 참고 정보가 질문과 관련 없거나 부족하면 추측하지 말고 상담사 연결을 안내하세요."
)

# 참고 문서(공용 DB financial_consulting_qa 의 컬럼명)에서 LLM 에 보여줄 필드
_DOC_FIELDS = (("question", "고객 질문"), ("answer", "상담사 답변"), ("output", "종합 답변"))


class OllamaError(RuntimeError):
    """Ollama 에 연결하지 못했거나 응답이 이상할 때. 호출한 쪽은 '상담사 연결 안내'로 대체하면 됩니다."""


def format_docs(docs: List[dict]) -> str:
    """검색된 문서(컬럼별 dict)들을 '[참고 N] 라벨: 내용' 텍스트로 만든다."""
    blocks = []
    for i, doc in enumerate(docs, start=1):
        lines = [f"[참고 {i}]"] + [f"{label}: {doc[key]}" for key, label in _DOC_FIELDS if doc.get(key)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_messages(question: str, docs: Optional[List[dict]] = None) -> List[dict]:
    """Ollama /api/chat 에 보낼 messages(system/user)를 만든다."""
    user = f"### 고객 문의\n{question}"
    if docs:
        user = f"### 참고 정보\n{format_docs(docs)}\n\n{user}"
    return [{"role": "system", "content": INSTRUCTION + _STYLE}, {"role": "user", "content": user}]


def generate(question: str, docs: Optional[List[dict]] = None) -> str:
    """질문(+RAG 검색 문서)을 보내 base 모델의 답변 텍스트를 받는다."""
    body = {
        "model": OLLAMA_MODEL,
        "messages": build_messages(question, docs),
        "stream": False,
        "options": {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS, "num_ctx": LLM_NUM_CTX},
    }
    try:
        r = httpx.post(f"{OLLAMA_HOST}/api/chat", json=body, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise OllamaError(f"Ollama 호출 실패({OLLAMA_HOST}, {OLLAMA_MODEL}): {e.__class__.__name__}: {e}") from e
