"""환경변수 설정. .env 파일 또는 시스템 환경변수에서 읽습니다."""
import os

from dotenv import load_dotenv

load_dotenv()

AI_MOCK_MODE = os.getenv("AI_MOCK_MODE", "true").lower() == "true"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct")
LLM_ADAPTER_PATH = os.getenv("LLM_ADAPTER_PATH", "")
LLM_DEVICE = os.getenv("LLM_DEVICE", "auto").strip().lower()
LLM_LOAD_IN_4BIT = os.getenv("LLM_LOAD_IN_4BIT", "false").strip().lower()
LLM_ADAPTER_ROOT = os.getenv("LLM_ADAPTER_ROOT", "")
VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", "data/processed/index")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1")
# Timeout hierarchy: browser 90s > web->AI 70s > AI (search up to ~22s + LLM 40s)
VLLM_TIMEOUT = float(os.getenv("VLLM_TIMEOUT", "40"))