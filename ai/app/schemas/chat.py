"""web ↔ ai 가 주고받는 데이터 형식. 자세한 설명은 docs/api-spec.md 참고."""
from typing import List, Literal, Optional

from pydantic import BaseModel


class ChatTurn(BaseModel):
    """이번 상담의 이전 발화 1건 (후속 질문을 이해하기 위한 대화 기록)"""
    role: Literal["user", "assistant"]   # 고객 = user, AI = assistant
    content: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: List[ChatTurn] = []   # 직전 대화(오래된 순). 없으면 질문 한 건으로만 처리


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
