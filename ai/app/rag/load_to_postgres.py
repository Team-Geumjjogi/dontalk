"""
PostgresSQL(pgvector) DB에 데이터 적재
 
dontalk/
 ├─ .env                                     (DB 접속 정보)
 ├─ ai/app/rag/load_to_postgres.py           ← 이 파일
 └─ data/processed/df_add_embedding.parquet  (입력: embedder.py 결과)
 
실행:
    python load_to_postgres.py                    # 전체 적재 + 인덱스 생성
    python load_to_postgres.py --limit 100        # 상위 100건만 테스트 적재
    python load_to_postgres.py --truncate         # 테이블 비운 뒤 다시 적재
    python load_to_postgres.py --skip-duplicates  # qa_id 중복 행은 건너뛰고 적재
    python load_to_postgres.py --index-only       # 적재 없이 인덱스만 생성
 
.env 예시:
    DB_HOST=localhost
    POSTGRESQL_PORT=5432
    POSTGRESQL_USER=...
    POSTGRESQL_PASSWORD=...
    POSTGRESQL_DBNAME=...
"""


from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from psycopg2 import sql
from psycopg2.extras import execute_values


# ----------------------------------------------------------------
# Settings (Path etc.)
# ----------------------------------------------------------------
# 가장 상위 디렉토리로 이동 후 실행 위치와 무관하게 해당 파일 기준으로 경로 계산
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 실행 위치와 무관하게 프로젝트 루트의 .env를 읽음 (없으면 기본 탐색)
_env_path = PROJECT_ROOT / ".env"
load_dotenv(_env_path if _env_path.exists() else None)


@dataclass
class LoaderConfig:

    project_root: Path = PROJECT_ROOT
    table_name: str = "financial_consulting_qa"
    batch_size: int = 500                   # 한 번에 INSERT할 행 수
    maintenance_work_mem: str = "1GB"       # HNSW 빌드 시 메모리 (클수록 빠름)
    parquet_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.parquet_path = (
            self.project_root / "data" / "processed" / "df_add_embedding.parquet"
        )

    @staticmethod
    def db_config() -> dict[str, str]:
        env_keys = {
            "host": "DB_HOST",
            "port": "POSTGRESQL_PORT",
            "user": "POSTGRESQL_USER",
            "password": "POSTGRESQL_PASSWORD",
            "dbname": "POSTGRESQL_DBNAME",
        }
        config = {k: os.getenv(v) for k, v in env_keys.items()}
        missing = [env_keys[k] for k, v in config.items() if not v]
        if missing:
            raise EnvironmentError(f".env에 다음 값이 없습니다: {missing}")
        return config


# ----------------------------------------------------------------
# Column Settings (테이블 스키마와 순서 일치)
# ----------------------------------------------------------------
TEXT_COLUMNS: list[str] = [
    "qa_id", "instruction", "question", "answer", "follow_up_question", "output",
    "full_source", "consulting_category", "consulting_topic", "qa_topic",
    "consulting_purpose",
]
EMBEDDING_COLUMN = "embedding_q"
INSERT_COLUMNS: list[str] = TEXT_COLUMNS + [EMBEDDING_COLUMN]

# 빈 문자열("")을 NULL로 저장할 컬럼
EMPTY_TO_NULL: list[str] = [
    "answer", "follow_up_question", "output",
    "consulting_topic", "qa_topic", "consulting_purpose",
]


# ----------------------------------------------------------------
# Loader
# ----------------------------------------------------------------
class PostgresVectorLoader:

    def __init__(self, config: LoaderConfig | None = None) -> None:
        self.config = config or LoaderConfig()
        self.table = sql.Identifier(self.config.table_name)

    # ---------------- Data ----------------
    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        path = self.config.parquet_path
        if not path.exists():
            raise FileNotFoundError(
                f"입력 파일이 없습니다: {path}\n먼저 embedder.py를 실행하세요."
            )

        print("임베딩 파일 로딩 중...")
        df = pd.read_parquet(path)
        print(f"전체 행 수: {len(df)}")

        missing = [c for c in INSERT_COLUMNS if c not in df.columns]
        if missing:
            raise KeyError(f"parquet에 필요한 컬럼이 없습니다: {missing}")

        if limit is not None:
            df = df.head(limit).copy()
            print(f"[TEST] 상위 {limit}건만 적재합니다.")

        n_dup = df["qa_id"].duplicated().sum()
        if n_dup:
            print(f"[WARNING] qa_id 중복 {n_dup}건 (PRIMARY KEY라면 적재 시 충돌)")

        return df

    @staticmethod
    def embedding_dim(df: pd.DataFrame) -> int:
        dims = df[EMBEDDING_COLUMN].map(len)
        if dims.nunique() != 1:
            raise ValueError(f"임베딩 차원이 일정하지 않습니다: {dims.unique()}")
        return int(dims.iloc[0])

    # df 데이터를 DB에 INSERT할 수 있는 튜플 리스트로 변환
    @staticmethod
    def build_records(df: pd.DataFrame) -> list[tuple]:
        text_df = df[TEXT_COLUMNS].astype(object)
        text_df = text_df.where(text_df.notna(), None)
        for col in EMPTY_TO_NULL:
            text_df[col] = text_df[col].map(lambda v: None if v == "" else v)

        embeddings = [np.asarray(e, dtype=np.float32) for e in df[EMBEDDING_COLUMN]]

        return [
            (*values, emb)
            for values, emb in zip(text_df.itertuples(index=False, name=None), embeddings)
        ]

    # ---------------- DB ----------------
    def connect(self):
        print("DB 연결 중...")
        conn = psycopg2.connect(**self.config.db_config())
        # vector 확장이 있어야 register_vector가 동작
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        register_vector(conn)
        print("DB 연결 성공")
        return conn


    # 테이블 생성 (이미 있으면 건너뜀)
    def ensure_table(self, conn, dim: int) -> None:
        text_cols = sql.SQL(",\n").join(
            sql.SQL("{} TEXT").format(sql.Identifier(c)) for c in TEXT_COLUMNS[1:]
        )
        query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {table} (
                qa_id TEXT PRIMARY KEY,
                {text_cols},
                {emb} vector({dim})
            );
        """).format(
            table=self.table,
            text_cols=text_cols,
            emb=sql.Identifier(EMBEDDING_COLUMN),
            dim=sql.Literal(dim),
        )
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()

    # 테이블 초기화
    def truncate(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("TRUNCATE TABLE {};").format(self.table))
        conn.commit()
        print(f"테이블 초기화: {self.config.table_name}")

    # 테이블 내 데이터 적재
    def insert_records(self, conn, records: list[tuple], skip_duplicates: bool = False) -> None:
        query = sql.SQL("INSERT INTO {table} ({cols}) VALUES %s").format(
            table=self.table,
            cols=sql.SQL(", ").join(map(sql.Identifier, INSERT_COLUMNS)),
        )
        if skip_duplicates:
            query += sql.SQL(" ON CONFLICT (qa_id) DO NOTHING")

        total = len(records)
        bs = self.config.batch_size
        print(f"총 {total}건을 {bs}건씩 나눠서 적재 시작...")
        t0 = time.time()

        with conn.cursor() as cur:
            query_str = query.as_string(conn)
            for i in range(0, total, bs):
                batch = records[i:i + bs]
                try:
                    execute_values(cur, query_str, batch)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[ERROR] 배치 {i}~{i + len(batch)} 적재 실패: {e}")
                    raise
                print(f"진행: {min(i + bs, total)}/{total}")

        print(f"전체 적재 완료! ({time.time() - t0:.1f}초)")

    def count_rows(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {};").format(self.table))
            count = cur.fetchone()[0]
        print(f"현재 테이블 전체 행 수: {count}")
        return count

    # 데이터 적재 후 HNSW 인덱스 생성 (이미 있을 경우 건너뜀)
    # 검색 속도를 높이기 위해 활용됨
    def create_hnsw_index(self, conn) -> None:
        index_name = f"idx_{self.config.table_name}_{EMBEDDING_COLUMN}"
        print(f"HNSW 인덱스 생성 중: {index_name}")
        t0 = time.time()

        with conn.cursor() as cur:
            # 세션 단위 설정: 빌드 메모리 증가 (부족하면 빌드가 매우 느려짐)
            cur.execute(
                sql.SQL("SET maintenance_work_mem = {};").format(
                    sql.Literal(self.config.maintenance_work_mem)
                )
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {idx} ON {table} "
                    "USING hnsw ({emb} vector_cosine_ops);"
                ).format(
                    idx=sql.Identifier(index_name),
                    table=self.table,
                    emb=sql.Identifier(EMBEDDING_COLUMN),
                )
            )
            # 통계 갱신 → 플래너가 인덱스를 제대로 선택하도록
            cur.execute(sql.SQL("ANALYZE {};").format(self.table))
        conn.commit()
        print(f"HNSW 인덱스 준비 완료 ({time.time() - t0:.1f}초)")

    # ---------------- Run ----------------
    def run(
        self,
        limit: int | None = None,
        truncate: bool = False,
        skip_duplicates: bool = False,
        create_index: bool = True,
        index_only: bool = False,
    ) -> None:
        conn = self.connect()
        try:
            if not index_only:
                df = self.load_dataframe(limit)
                dim = self.embedding_dim(df)
                print(f"임베딩 차원: {dim}")

                self.ensure_table(conn, dim)
                if truncate:
                    self.truncate(conn)

                records = self.build_records(df)
                self.insert_records(conn, records, skip_duplicates)
                self.count_rows(conn)

            if create_index or index_only:
                self.create_hnsw_index(conn)
        finally:
            conn.close()


# ----------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="parquet → PostgreSQL(pgvector) 적재")
    parser.add_argument("--limit", type=int, default=None,
                        help="상위 N건만 테스트 적재 (기본: 전체)")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="INSERT 배치 크기 (기본: 500)")
    parser.add_argument("--truncate", action="store_true",
                        help="적재 전 테이블 비우기")
    parser.add_argument("--skip-duplicates", action="store_true",
                        help="qa_id 중복 행은 건너뛰기 (ON CONFLICT DO NOTHING)")
    parser.add_argument("--no-index", action="store_true",
                        help="적재 후 HNSW 인덱스를 생성하지 않음")
    parser.add_argument("--index-only", action="store_true",
                        help="적재 없이 HNSW 인덱스만 생성")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = LoaderConfig(batch_size=args.batch_size)
    loader = PostgresVectorLoader(config)
    loader.run(
        limit=args.limit,
        truncate=args.truncate,
        skip_duplicates=args.skip_duplicates,
        create_index=not args.no_index,
        index_only=args.index_only,
    )


if __name__ == "__main__":
    main()