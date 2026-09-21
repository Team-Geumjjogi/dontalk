"""web ↔ ai 가 주고받는 데이터 형식. 자세한 설명은 docs/api-spec.md 참고."""
from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    message: str


class Source(BaseModel):
    """답변의 근거로 검색된 문서 1건"""
    doc_id: str
    category: str          # 은행 / 보험 / 증권
    topic: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    category: Optional[str] = None     # 판단된 금융 분야 (은행/보험/증권)
    topic: Optional[str] = None        # 판단된 상담 주제
    confidence: float = 0.0            # 분야 판단 확신도 (0~1)
    sources: List[Source] = []         # RAG 검색 근거
    handoff_needed: bool = False       # True면 상담사 연결 제안
    handoff_reason: Optional[str] = None
