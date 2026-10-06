"""질문 → 팀 공용 DB 의 두 테이블에서 각각 유사 문서 Top-K 검색 후 하나의 리스트로 합쳐 반환 (질의용, 읽기 전용).

  qa        : 과거 질의응답 80,000건 (financial_consulting_qa)      → WHERE consulting_situation = '일반문의' 적용
  crawling  : 크롤링 데이터 (financial_consulting_qa_crawling)      → 조건 없이 전체에서 검색

테이블마다 SQL 이 달라서 TableSpec 으로 테이블별 설정(테이블명/조회 컬럼/WHERE 조건/임베딩 컬럼)을 따로 둔다.
질문 임베딩은 한 번만 만들어 두 테이블에 같이 쓴다.
두 테이블의 결과는 같은 컬럼(question, answer, consulting_category, consulting_topic + similarity, source)으로
맞춰서 similarity 내림차순의 한 리스트로 반환한다. (기존 search() 와 같은 List[dict] 형태)

적재(임베딩 → DB)는 load_to_postgres.py / embedder.py 담당이고, 이 파일은 조회만 합니다.
접속 정보는 .env 의 DB_* 입니다 (로컬 docker 의 POSTGRES_* / DATABASE_URL 과는 별개).
  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
  DB_SSLMODE(기본 require) DB_SSLNEGOTIATION(기본 direct) DB_CONNECT_TIMEOUT(기본 10)
  DB_TABLE_QA(기본 financial_consulting_qa; 예전 DB_TABLE 도 계속 인식)
  DB_TABLE_CRAWLING(기본 financial_consulting_qa_crawling)
  DB_QUERY_TIMEOUT(기본 6초: 이 시간 안에 응답이 없으면 연결을 버리고 새로 연결해 한 번 더 시도)
  RAG_TOP_K(기본 5)  RAG_TOP_K_QA / RAG_TOP_K_CRAWLING (테이블별로 따로 주고 싶을 때, 기본은 RAG_TOP_K)

원격 DB 연결은 Wi-Fi 변경/절전/서버 쪽 정리로 조용히 끊길 수 있다. 그러면 쿼리가 에러 없이 한참 멈추는데,
(1) TCP keepalive, (2) 쿼리 타임아웃(워치독), (3) 연결을 버리고 재시도 로 멈춤 대신 에러가 나서 상담사 이관 안내로 넘어가게 한다.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as QueryTimeout
from dataclasses import dataclass
from threading import Lock, Thread
from typing import List, Optional, Tuple

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.rows import dict_row

from app.core import config

load_dotenv()
logger = logging.getLogger(__name__)

TOP_K = int(os.getenv("RAG_TOP_K", "5"))
QUERY_TIMEOUT = float(os.getenv("DB_QUERY_TIMEOUT", "6"))
_EMBEDDING_MODEL = config.EMBEDDING_MODEL or "dragonkue/snowflake-arctic-embed-l-v2.0-ko"

# 두 테이블 결과를 맞출 공통 컬럼. 반환 row 에는 이 컬럼 + similarity + source 가 들어간다.
COMMON_COLUMNS: Tuple[str, ...] = ("question", "answer", "consulting_category", "consulting_topic")


@dataclass(frozen=True)
class TableSpec:
    source: str                 # 결과 row 의 "source" 값 ("qa" / "crawling")
    table: str                  # 테이블명
    columns: Tuple[str, ...]    # SELECT 할 컬럼 (임베딩 컬럼은 거리 계산에만 쓰므로 제외). COMMON_COLUMNS 를 모두 포함해야 한다
    top_k: int                  # 이 테이블에서 가져올 개수
    embedding_column: str = "embedding_q"  # 고객 질문만 임베딩한 컬럼
    filter_column: Optional[str] = None    # WHERE {filter_column} = {filter_value}. None 이면 WHERE 없음
    filter_value: Optional[str] = None


SPEC_QA = TableSpec(
    source="qa",
    table=os.getenv("DB_TABLE_QA") or os.getenv("DB_TABLE", "financial_consulting_qa"),
    columns=COMMON_COLUMNS,
    top_k=int(os.getenv("RAG_TOP_K_QA", TOP_K)),
    filter_column="consulting_situation",
    filter_value="일반문의",
)
SPEC_CRAWLING = TableSpec(
    source="crawling",
    table=os.getenv("DB_TABLE_CRAWLING", "financial_consulting_qa_crawling"),
    columns=COMMON_COLUMNS,
    top_k=int(os.getenv("RAG_TOP_K_CRAWLING", TOP_K)),
)
SPECS: Tuple[TableSpec, ...] = (SPEC_QA, SPEC_CRAWLING)

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


def _embed_query(query: str):
    """질문 쪽은 반드시 prompt_name="query" 로 인코딩해야 한다 (임베딩 모델의 비대칭 규칙)."""
    return _get_model().encode(query.strip(), prompt_name="query", normalize_embeddings=True)


def _build_statement(spec: TableSpec, vec, limit: int):
    """테이블별 SQL 과 파라미터. WHERE 가 있는 테이블(qa)과 없는 테이블(crawling)의 SQL 이 다르다."""
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in spec.columns)
    emb = sql.Identifier(spec.embedding_column)
    table = sql.Identifier(spec.table)

    if spec.filter_column is None:
        statement = sql.SQL(
            "SELECT {cols}, {emb} <=> %s AS distance FROM {table} ORDER BY {emb} <=> %s LIMIT %s"
        ).format(cols=cols, emb=emb, table=table)
        return statement, (vec, vec, limit)

    statement = sql.SQL(
        "SELECT {cols}, {emb} <=> %s AS distance FROM {table} "
        "WHERE {fcol} = %s ORDER BY {emb} <=> %s LIMIT %s"
    ).format(cols=cols, emb=emb, table=table, fcol=sql.Identifier(spec.filter_column))
    return statement, (vec, spec.filter_value, vec, limit)


def _search_table(spec: TableSpec, vec, top_k: Optional[int] = None) -> List[dict]:
    """한 테이블에서 벡터 유사도 Top-K. 공통 컬럼 + similarity(=1-코사인거리) + source 로 맞춰서 돌려준다."""
    limit = spec.top_k if top_k is None else top_k
    statement, params = _build_statement(spec, vec, limit)
    rows = _query(statement, params)
    return [
        {
            **{c: row.get(c) for c in COMMON_COLUMNS},
            "similarity": 1.0 - float(row["distance"]),
            "source": spec.source,
        }
        for row in rows
    ]


def search_qa(query: str, top_k: Optional[int] = None) -> List[dict]:
    """과거 질의응답 테이블(일반문의)만 조회."""
    if not query or not query.strip():
        return []
    return _search_table(SPEC_QA, _embed_query(query), top_k)


def search_crawling(query: str, top_k: Optional[int] = None) -> List[dict]:
    """크롤링 테이블만 조회."""
    if not query or not query.strip():
        return []
    return _search_table(SPEC_CRAWLING, _embed_query(query), top_k)


def _postprocess(rows: List[dict]) -> List[dict]:
    """합쳐진 RAG 결과를 걸러서 튜닝 모델에 넘길 데이터만 고르는 자리.

    지금은 similarity 내림차순 정렬만 한다. 추가 처리 로직(유사도 컷오프, 중복 제거, 개수 제한 등)은 여기에 넣는다.
    """
    return sorted(rows, key=lambda r: r["similarity"], reverse=True)


def search(query: str) -> List[dict]:
    """질문과 가장 비슷한 문서를 두 테이블에서 각각 Top-K 조회해 하나의 리스트로 반환한다.

    각 row: question, answer, consulting_category, consulting_topic, similarity, source("qa"/"crawling").

    - 질문 임베딩은 한 번만 만든다.
    - 한 테이블 조회가 실패하면 그 테이블은 건너뛰고 경고만 남긴다. 모든 테이블이 실패하면 예외를 그대로 올린다
      (→ 상담사 이관 안내로 넘어가는 기존 동작 유지).
    """
    if not query or not query.strip():
        return []

    vec = _embed_query(query)
    merged: List[dict] = []
    errors: List[Exception] = []
    for spec in SPECS:
        try:
            merged.extend(_search_table(spec, vec))
        except Exception as e:  # noqa: BLE001 - 한 테이블 실패가 다른 테이블 결과를 막지 않게 한다
            logger.warning("RAG 조회 실패 (%s / %s): %s", spec.source, spec.table, e)
            errors.append(e)
    if len(errors) == len(SPECS):
        raise errors[-1]
    return _postprocess(merged)