"""train / valid / test 분할.

★ 프로젝트에서 가장 먼저 확정해야 하는 규칙입니다.
  - 분할 단위: source_id (상담 1건). 같은 상담의 QA는 항상 같은 split.
  - 해시 기반이라 파일 공유 없이도 팀원 모두 같은 결과를 얻습니다. (seed 가 같으면)
  - test 는 RAG Knowledge Base 와 LLM 학습 데이터에서 반드시 제외합니다.
"""
import hashlib


def assign_split(source_id: str, seed: int = 42, ratios=(0.8, 0.1, 0.1)) -> str:
    h = int(hashlib.md5(f"{seed}:{source_id}".encode("utf-8")).hexdigest(), 16) % 10_000 / 10_000
    train, valid, _ = ratios
    if h < train:
        return "train"
    if h < train + valid:
        return "valid"
    return "test"
