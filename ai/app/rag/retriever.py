"""질문 → 팀 공용 DB(financial_consulting_qa)에서 유사 문서 Top-K 검색 (질의용, 읽기 전용).

적재(임베딩 → DB)는 load_to_postgres.py / embedder.py 담당이고, 이 파일은 조회만 합니다.
접속 정보는 .env 의 DB_* 입니다 (로컬 docker 의 POSTGRES_* / DATABASE_URL 과는 별개).
  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
  DB_SSLMODE(기본 require) DB_SSLNEGOTIATION(기본 direct) DB_CONNECT_TIMEOUT(기본 10) DB_TABLE(기본 financial_consulting_qa)
  DB_QUERY_TIMEOUT(기본 6초: 이 시간 안에 응답이 없으면 연결을 버리고 새로 연결해 한 번 더 시도)
  RAG_TOP_K(기본 5)

원격 DB 연결은 Wi-Fi 변경/절전/서버 쪽 정리로 조용히 끊길 수 있다. 그러면 쿼리가 에러 없이 한참 멈추는데,
(1) TCP keepalive, (2) 쿼리 타임아웃(워치독), (3) 연결을 버리고 재시도 로 멈춤 대신 에러가 나서 상담사 이관 안내로 넘어가게 한다.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as QueryTimeout
from threading import Lock, Thread
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
QUERY_TIMEOUT = float(os.getenv("DB_QUERY_TIMEOUT", "6"))
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
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kb-query")  # 쿼리를 별도 스레드에서 돌려 타임아웃을 걸 수 있게 한다


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
        # 공용 DB 보호: 서버 쪽에서 쓰기 차단 + 오래 걸리는 쿼리 중단
        options=f"-c default_transaction_read_only=on -c statement_timeout={int(QUERY_TIMEOUT * 1000)}",
        keepalives=1, keepalives_idle=15, keepalives_interval=5, keepalives_count=3,  # 끊긴 연결을 약 30초 안에 알아챈다
        tcp_user_timeout=15000,  # 응답 없는 전송을 15초 뒤 포기 (Linux 에서만 동작, 맥에서는 무시됨)
    )
    if os.getenv("DB_SSLNEGOTIATION", "direct"):
        kwargs["sslnegotiation"] = os.getenv("DB_SSLNEGOTIATION", "direct")
    conn = psycopg.connect(**kwargs, autocommit=True, row_factory=dict_row)
    register_vector(conn)
    return conn


def _run(conn, statement, params) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchall()


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _drop_connection() -> None:
    """응답 없는/끊긴 연결은 버린다. 닫는 동작 자체가 멈출 수 있어 별도 스레드에서 시도하고, 다음 호출이 새로 연결한다."""
    global _conn
    broken, _conn = _conn, None
    if broken is not None:
        Thread(target=_close_quietly, args=(broken,), daemon=True).start()


def _query(statement, params) -> List[dict]:
    """연결을 재사용한다. 끊겼거나 QUERY_TIMEOUT 안에 응답이 없으면 연결을 버리고 새로 연결해서 한 번만 다시 시도한다."""
    global _conn
    last_error: Exception = RuntimeError("공용 DB 조회 실패")
    with _conn_lock:
        for _ in range(2):
            try:
                if _conn is None or _conn.closed:
                    _conn = _connect()
                return _executor.submit(_run, _conn, statement, params).result(timeout=QUERY_TIMEOUT)
            except QueryTimeout:
                last_error = TimeoutError(f"공용 DB 응답이 {QUERY_TIMEOUT:g}초 안에 오지 않았습니다")
            except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                last_error = e
            _drop_connection()
    raise last_error


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
