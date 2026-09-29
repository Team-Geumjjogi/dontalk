# ============================================================
# Postgres(pgvector)에 데이터 적재
# ============================================================

import os
import psycopg2
from dotenv import load_dotenv
import pandas as pd
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector

load_dotenv()

POSTGRESQL_PORT = os.getenv("POSTGRESQL_PORT")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD")
POSTGRESQL_DBNAME = os.getenv("POSTGRESQL_DBNAME")

# --------------------------------------------------------
# 1. 설정값
# --------------------------------------------------------
PARQUET_PATH = "./data/raw/embeddings_output.parquet" 

DB_CONFIG = {
    "host": "localhost",       # 로컬 Docker Desktop 기준. 클라우드 VM이면 VM 공인 IP로 변경
    "port": POSTGRESQL_PORT,
    "user": POSTGRESQL_USER,
    "password": POSTGRESQL_PASSWORD,
    "dbname": POSTGRESQL_DBNAME,
}

# 먼저 소량으로 테스트하고 싶을 때 사용 (None이면 전체 적재)
TEST_LIMIT = None   # 예: 100 으로 바꾸면 100건만 테스트 적재

TABLE_NAME = "financial_consulting_qa"
BATCH_SIZE = 500   # 한 번에 INSERT할 행 수. 8만건 / 500 = 160번 정도 나눠서 적재

# --------------------------------------------------------
# 2. 데이터 로드
# --------------------------------------------------------
print("임베딩 파일 로딩 중...")
df = pd.read_parquet(PARQUET_PATH)
print(f"전체 행 수: {len(df)}")

if TEST_LIMIT is not None:
    df = df.head(TEST_LIMIT).copy()
    print(f"!!!!!!\n테스트 모드: 상위 {TEST_LIMIT}건만 적재합니다.\n!!!!!!")

# --------------------------------------------------------
# 3. DB 연결 + pgvector 타입 등록
#    register_vector를 해줘야 psycopg2가 파이썬 list를 vector 타입으로 자동 변환해줌
# --------------------------------------------------------
print("DB 연결 중...")
conn = psycopg2.connect(**DB_CONFIG)       # 딕셔너리를 key=value로 풀어서 입력해줌
register_vector(conn)       # 파이썬의 list/numpy array를 pgvector vector 타입으로 변환해주는 함수 등록
cur = conn.cursor()       #파이썬과 DB 연결 후 SQL 실행을 위한 커서 생성
print("DB 연결 성공")

# --------------------------------------------------------
# 4. INSERT할 컬럼 순서 정의 (테이블 스키마와 순서 일치시킴)
# --------------------------------------------------------
insert_columns = [
    "qa_id", "instruction", "question", "answer", "follow_up_question", "output",
    "full_source", "consulting_category", "consulting_topic", "qa_topic",
    "consulting_purpose", "embedding_q", "embedding_i", "embedding_full",
]

# --------------------------------------------------------
# 5. 행 데이터를 튜플로 변환
#    embedding 컬럼은 numpy/list 형태 그대로 넘기면 register_vector가 처리해줌
# --------------------------------------------------------
def row_to_tuple(row):
    return (
        row["qa_id"],
        row["instruction"],
        row["question"],
        row["answer"] if row["answer"] != "" else None,
        row["follow_up_question"] if row["follow_up_question"] != "" else None,
        row["output"] if row["output"] != "" else None,
        row["full_source"],
        row["consulting_category"],
        row.get("consulting_topic") or None,
        row.get("qa_topic") or None,
        row.get("consulting_purpose") or None,
        row["embedding_q"],
        row["embedding_i"],
        row["embedding_full"],
    )

records = [row_to_tuple(row) for _, row in df.iterrows()]
# +) df.iterrows()로 꺼낸 row는 pandas의 Series 객체이므로, row["컬럼명"]으로 접근 가능.
#    psycopg2는 SQL의 %s 자리에 들어갈 값을 튜플로 받음
#    > 즉, INSERT에 바로 쓸 수 있는 튜플 형태로 바꾸어 주는 작업 필요

# --------------------------------------------------------
# 6. 데이터 INSERT (execute_values로 여러 행을 한 번에 전송 → 8만 건도 빠르게 처리)
# --------------------------------------------------------
insert_sql = f"""
    INSERT INTO {TABLE_NAME} ({", ".join(insert_columns)})
    VALUES %s
"""

# !!! 적재 중간에 실패했을 때 사용 or 코드 수정하기
# ON CONFLICT (qa_id) DO NOTHING; 를 추가하면, qa_id가 중복되는 경우 해당 행은 건너뛰고 나머지 행은 계속 적재됨
# insert_sql = f"""
#     INSERT INTO {TABLE_NAME} ({", ".join(insert_columns)})
#     VALUES %s
#     ON CONFLICT ({insert_columns[0]}) DO NOTHING;
# """


print(f"총 {len(records)}건을 {BATCH_SIZE}건씩 나눠서 적재 시작...")
total = len(records)
for i in range(0, total, BATCH_SIZE):
    batch = records[i:i + BATCH_SIZE]
    try:
        execute_values(cur, insert_sql, batch)       # execute_values는 여러 행을 한 번에 INSERT할 수 있는 psycopg2 함수 (이 상태에서는 아직 DB에 반영되지 않음)
        conn.commit()       # 커밋을 해야 실제 DB에 반영됨. > 실행되는 순간 DB에 영구 저장
        print(f"진행: {min(i + BATCH_SIZE, total)}/{total}")
    except Exception as e:
        conn.rollback()       # 확정되지 않은 변경 모두 취소
        print(f"!!!!!!\n배치 {i}~{i+BATCH_SIZE} 적재 중 오류 발생: {e}\n!!!!!!")
        raise

print("전체 적재 완료!")

# --------------------------------------------------------
# 7. 적재 결과 확인
# --------------------------------------------------------
cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME};")
count = cur.fetchone()[0] # 첫 번째 행의 첫 번째 값을 꺼내 옴 (데이터 개수 확인에 용이)
print(f"현재 테이블 전체 행 수: {count}")

cur.close()
conn.close()


# +) 이후 별도로 psql에서 'embedding_q', 'embedding_i', 'embedding_full' 컬럼에 대한 인덱스 생성 필요