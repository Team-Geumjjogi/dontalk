from fastapi import APIRouter

from app.core import config

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "mock_mode": config.AI_MOCK_MODE}
