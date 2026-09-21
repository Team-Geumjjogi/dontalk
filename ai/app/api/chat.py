from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """질문을 받아 답변(+분야, 근거, 상담사 연결 필요 여부)을 돌려줍니다."""
    return chat_service.answer(req)
