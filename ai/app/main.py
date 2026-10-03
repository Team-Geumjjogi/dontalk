"""AI 서버 시작 파일.

실행 (ai/ 폴더 안에서):
    uvicorn app.main:app --reload --port 8000
확인:  http://localhost:8000/health   /   http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import chat, health
from app.core import config
from app.services import chat_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")  # 요청별 소요 시간 로그가 터미널에 보이게


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.AI_MOCK_MODE:
        chat_service.warm_up()  # 임베딩 모델/DB 연결 미리 준비 (첫 질문 지연 방지)
    yield


app = FastAPI(title="DonTalk AI Server", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router)
