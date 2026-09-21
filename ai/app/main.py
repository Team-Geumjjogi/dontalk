"""AI 서버 시작 파일.

실행 (ai/ 폴더 안에서):
    uvicorn app.main:app --reload --port 8000
확인:  http://localhost:8000/health   /   http://localhost:8000/docs
"""
from fastapi import FastAPI

from app.api import chat, health

app = FastAPI(title="DonTalk AI Server")
app.include_router(health.router)
app.include_router(chat.router)
