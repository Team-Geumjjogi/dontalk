"""질문 → 팀 공용 DB(financial_consulting_qa)에서 유사 문서 Top-K 검색 (질의용, 읽기 전용).

적재(임베딩 → DB)는 load_to_postgres.py / embedder.py 담당이고, 이 파일은 조회만 합니다.
접속 정보는 .env 의 DB_* 입니다 (로컬 docker 의 POSTGRES_* / DATABASE_URL 과는 별개).
  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
  DB_SSLMODE(기본 require) DB_SSLNEGOTIATION(기본 direct) DB_CONNECT_TIMEOUT(기본 10) DB_TABLE(기본 financial_consulting_qa)
  RAG_TOP_K(기본 5)
"""
import os
from threading import Lock
from typing import List

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.rows import dict_row

from app.core import config

load_dotenv()

DB_TABLE = os.getenv("DB_TABLE", "financial_consulting_qa")
EMBEDDING_COLUMN = "embedding_q"  # 고객 질문만 임베딩한 컬럼
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
_EMBEDDING_MODEL = config.EMBEDDING_MODEL or "dragonkue/snowflake-arctic-embed-l-v2.0-ko"

# LLM 에 쓰는 개별 컬럼 + 분야 판단용 메타데이터 (컬럼을 텍스트로 합치지 않고 그대로 가져온다)
_COLUMNS = (
    "qa_id", "question", "answer", "follow_up_question", "output", "full_source",
    "consulting_category", "consulting_topic", "qa_topic", "consulting_purpose",
)

_model = None
_model_lock = Lock()
_conn = None
_conn_lock = Lock()


def _get_model():
    """질문 임베딩 모델. 맥 메모리를 아끼려고 CPU 로 로드하고 프로세스당 한 번만 로드한다."""
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(_EMBEDDING_MODEL, device="cpu")
        return _model


def _connect():
    kwargs = dict(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        options="-c default_transaction_read_only=on",  # 공용 DB 보호: 서버 쪽에서 쓰기 차단
    )
    if os.getenv("DB_SSLNEGOTIATION", "direct"):
        kwargs["sslnegotiation"] = os.getenv("DB_SSLNEGOTIATION", "direct")
    conn = psycopg.connect(**kwargs, autocommit=True, row_factory=dict_row)
    register_vector(conn)
    return conn


def _query(statement, params) -> List[dict]:
    """연결을 재사용하고, 끊겨 있으면 한 번만 다시 연결해서 재시도한다."""
    global _conn
    with _conn_lock:
        for attempt in (1, 2):
            try:
                if _conn is None or _conn.closed:
                    _conn = _connect()
                with _conn.cursor() as cur:
                    cur.execute(statement, params)
                    return cur.fetchall()
            except (psycopg.OperationalError, psycopg.InterfaceError):
                _conn = None
                if attempt == 2:
                    raise


def warm_up() -> None:
    """서버 시작 때 호출해서 첫 질문의 모델 로딩/DB 연결 지연을 없앤다."""
    _get_model()
    _query(sql.SQL("SELECT 1 AS ok"), None)


def search(query: str, top_k: int = TOP_K) -> List[dict]:
    """질문과 가장 비슷한 과거 상담 Top-K. 각 문서는 컬럼별 dict + similarity(=1-코사인거리).

    질문 쪽은 반드시 prompt_name="query" 로 인코딩해야 한다 (임베딩 모델의 비대칭 규칙).
    """
    if not query or not query.strip():
        return []
    vec = _get_model().encode(query.strip(), prompt_name="query", normalize_embeddings=True)
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)
    emb = sql.Identifier(EMBEDDING_COLUMN)
    statement = sql.SQL(
        "SELECT {cols}, {emb} <=> %s AS distance FROM {table} ORDER BY {emb} <=> %s LIMIT %s"
    ).format(cols=cols, emb=emb, table=sql.Identifier(DB_TABLE))
    rows = _query(statement, (vec, vec, top_k))
    for row in rows:
        row["similarity"] = 1.0 - float(row.pop("distance"))
    return rows
