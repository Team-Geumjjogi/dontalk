"""환경변수 설정. .env 파일 또는 시스템 환경변수에서 읽습니다."""
import os

from dotenv import load_dotenv

load_dotenv()

AI_MOCK_MODE = os.getenv("AI_MOCK_MODE", "true").lower() == "true"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct")
LLM_ADAPTER_PATH = os.getenv("LLM_ADAPTER_PATH", "")
VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", "data/processed/index")
