"""
과거 사용자 질문을 임베딩하여 DataFrame에 추가한 뒤 parquet로 저장

dontalk/
 ├─ ai/app/rag/embedder.py        ← 이 파일
 └─ data/processed/
      ├─ df_output.xlsx           (입력: data_preprocessing.py 결과)
      ├─ checkpoints/             (청크 단위 중간 결과, 중단 후 재실행 시 이어서 처리)
      └─ df_add_embedding.parquet (출력)

실행:
    python embedder.py
    python embedder.py --input ../../../data/processed/df_output.xlsx     # 입력 파일 경로 설정 (기본: dontalk/data/processed/df_output.xlsx)
    python embedder.py --output ../../../data/processed/df_add_embedding.parquet     # 실행 결과 파일(parquet 파일) 경로 설정 (기본: dontalk/data/processed/df_add_embedding.parquet)
    python embedder.py --chunk-size 4000    # 청크 당 처리 행 수 설정 (기본: 8000)
    python embedder.py --reset              # 기존 체크포인트 삭제 후 처음부터 다시
    python embedder.py --limit 50           # 상위 50개의 데이터만 활용
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ----------------------------------------------------------------
# Settings (Path, Embedding_Model etc.)
# ----------------------------------------------------------------
# 가장 상위 디렉토리로 이동 후 실행 위치와 무관하게 해당 파일 기준으로 경로 계산
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class EmbedderConfig:

    project_root: Path = PROJECT_ROOT
    model_name: str = "dragonkue/snowflake-arctic-embed-l-v2.0-ko"
    chunk_size: int = 8000
    limit : int | None = None
    input_path: Path = field(init=False)
    output_path: Path = field(init=False)
    checkpoint_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        processed = self.project_root / "data" / "processed"
        self.input_path = processed / "df_output.xlsx"
        self.output_path = processed / "df_add_embedding.parquet"
        self.checkpoint_dir = processed / "checkpoints"


# ----------------------------------------------------------------
# Column / Embedding Settings
# ----------------------------------------------------------------
# 필요한 컬럼만 추출 + 스키마에 맞게 이름 변경
COLUMN_MAP: dict[str, str] = {
    "qa_data_qa_id": "qa_id",
    "qa_data_instruction": "instruction",
    "qa_data_input_question": "question",
    "qa_data_input_answer": "answer",
    "qa_data_input_follow_up_question": "follow_up_question",
    "qa_data_output": "output",
    "qa_data_full_source": "full_source",
    "consulting_consulting_category": "consulting_category",
    "consulting_consulting_topic": "consulting_topic",
    "qa_data_qa_topic": "qa_topic",
    "qa_data_consulting_purpose": "consulting_purpose",
    "qa_data_task_category": "task_category",
    "qa_data_consulting_situation": "consulting_situation",
}

# 임베딩할 컬럼: (원본 컬럼, 결과 컬럼, 배치 크기)
EMBEDDING_TARGETS: list[tuple[str, str, int]] = [
    ("question", "embedding_q", 32),
]


# ----------------------------------------------------------------
# Embedder
# ----------------------------------------------------------------
class QAEmbedder:

    def __init__(
        self,
        config: EmbedderConfig | None = None,
        column_map: dict[str, str] = COLUMN_MAP,
        targets: list[tuple[str, str, int]] = EMBEDDING_TARGETS,
    ) -> None:
        self.config = config or EmbedderConfig()
        self.column_map = column_map
        self.targets = targets
        self.model = None  # load_model()에서 로드

    # ---------------- Load ----------------
    def load_dataframe(self, input_path: Path | None = None) -> pd.DataFrame:
        input_path = Path(input_path or self.config.input_path)
        if not input_path.exists():
            raise FileNotFoundError(
                f"입력 파일이 없습니다: {input_path}\n"
                f"먼저 data_preprocessing.py를 실행하세요."
            )

        if input_path.suffix == ".parquet":
            df = pd.read_parquet(input_path)
        else:
            df = pd.read_excel(input_path)

        missing = [c for c in self.column_map if c not in df.columns]
        if missing:
            raise KeyError(f"입력 데이터에 필요한 컬럼이 없습니다: {missing}")

        df = df[list(self.column_map)].rename(columns=self.column_map).copy()

        if self.config.limit is not None:
            df = df.head(self.config.limit).copy()
            print(f"[TEST] 상위 {self.config.limit}건만 처리합니다.")

        for src_col, _, _ in self.targets:
            n_empty = df[src_col].isna().sum()
            if n_empty:
                print(f"[WARNING] '{src_col}' 결측치 {n_empty}건 → 빈 문자열로 대체")
            df[src_col] = df[src_col].fillna("").astype(str)

        print(f"전체 행 수: {len(df)}")
        return df

    def load_model(self) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"사용 디바이스: {device}")

        self.model = SentenceTransformer(self.config.model_name, device=device)
        print(f"모델 로드 완료: {self.config.model_name}")

    # ---------------- Encode ----------------
    def encode_texts(self, texts: list[str], batch_size: int) -> np.ndarray:
        if self.model is None:
            self.load_model()
        return self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,  # 청크 단위 로그로 대체
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

    def embed_chunk(self, df_chunk: pd.DataFrame) -> pd.DataFrame:
        df_chunk = df_chunk.copy()
        for src_col, dst_col, batch_size in self.targets:
            emb = self.encode_texts(df_chunk[src_col].tolist(), batch_size)
            # 행마다 1차원 float32 배열 → parquet에 list<float>로 저장됨
            df_chunk[dst_col] = list(emb)
        return df_chunk

    # ---------------- Checkpoint ----------------
    def _checkpoint_path(self, chunk_idx: int) -> Path:
        return self.config.checkpoint_dir / f"chunk_{chunk_idx:03d}.parquet"

    def _manifest(self, n_rows: int) -> dict[str, Any]:
        return {
            "model_name": self.config.model_name,
            "chunk_size": self.config.chunk_size,
            "n_rows": n_rows,
            "targets": [list(t[:2]) for t in self.targets],
        }

    # 체크포인트 폴더 준비 - 이전 실행과 설정(모델, 청크 크기, 행 수)이 다르면 청크 어긋나 중단
    def prepare_checkpoint_dir(self, n_rows: int, reset: bool = False) -> None:
        ckpt_dir = self.config.checkpoint_dir
        if reset and ckpt_dir.exists():
            shutil.rmtree(ckpt_dir)
            print(f"체크포인트 초기화: {ckpt_dir}")

        ckpt_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = ckpt_dir / "manifest.json"
        current = self._manifest(n_rows)

        if manifest_path.exists():
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            if saved != current:
                raise RuntimeError(
                    "기존 체크포인트와 현재 설정이 다릅니다.\n"
                    f"  기존: {saved}\n  현재: {current}\n"
                    "--reset 옵션으로 다시 실행하세요."
                )
        else:
            manifest_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # ---------------- Run ----------------
    def embed_all(self, df: pd.DataFrame) -> list[Path]:
        chunk_size = self.config.chunk_size
        n_chunks = (len(df) + chunk_size - 1) // chunk_size
        overall_start = time.time()
        chunk_paths: list[Path] = []

        for chunk_idx in range(n_chunks):
            ckpt_path = self._checkpoint_path(chunk_idx)
            chunk_paths.append(ckpt_path)

            # 이미 처리된 청크는 건너뛰기 (중단 후 재실행 시 이어서 처리)
            if ckpt_path.exists():
                print(f"청크 {chunk_idx + 1}/{n_chunks} 이미 처리됨, 건너뜀")
                continue

            start = chunk_idx * chunk_size
            end = min(start + chunk_size, len(df))

            t0 = time.time()
            df_chunk = self.embed_chunk(df.iloc[start:end])
            df_chunk.to_parquet(ckpt_path, index=False)

            elapsed = time.time() - t0
            total = time.time() - overall_start
            print(
                f"청크 {chunk_idx + 1}/{n_chunks} 완료 ({end - start}건, {elapsed:.1f}초) "
                f"| 누적 시간: {total / 60:.1f}분"
            )

        print("\n전체 청크 처리 완료!")
        return chunk_paths

    @staticmethod
    def merge_chunks(chunk_paths: list[Path]) -> pd.DataFrame:
        # glob 대신 이번 실행의 청크 목록만 병합 (남아 있는 예전 파일 혼입 방지)
        df_final = pd.concat(
            [pd.read_parquet(p) for p in chunk_paths], ignore_index=True
        )
        print(f"최종 병합 결과: {len(df_final)}건")
        return df_final

    def save(self, df: pd.DataFrame, output_path: Path | None = None) -> Path:
        output_path = Path(output_path or self.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        print(f"최종 파일 저장 완료: {output_path}")
        return output_path

    def run(
        self,
        input_path: Path | None = None,
        output_path: Path | None = None,
        reset: bool = False,
    ) -> pd.DataFrame:
        df = self.load_dataframe(input_path)
        self.prepare_checkpoint_dir(n_rows=len(df), reset=reset)

        chunk_paths = self.embed_all(df)
        df_final = self.merge_chunks(chunk_paths)

        if len(df_final) != len(df):
            raise RuntimeError(
                f"병합 결과 행 수({len(df_final)})가 원본({len(df)})과 다릅니다."
            )

        dim = len(df_final[self.targets[0][1]].iloc[0])
        print(f"임베딩 차원: {dim}")

        self.save(df_final, output_path)
        return df_final


# ----------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA 데이터 임베딩 → parquet 저장")
    parser.add_argument(
        "--input", type=Path, default=None,
        help="입력 파일 경로 (기본: dontalk/data/processed/df_output.xlsx)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="저장할 parquet 경로 (기본: dontalk/data/processed/df_add_embedding.parquet)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=8000,
        help="청크당 처리 행 수 (기본: 8000)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="기존 체크포인트를 삭제하고 처음부터 다시 처리",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="테스트용: 상위 N건만 처리 (기본: 전체)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = EmbedderConfig(chunk_size=args.chunk_size, limit=args.limit)
    embedder = QAEmbedder(config=config)
    embedder.run(input_path=args.input, output_path=args.output, reset=args.reset)


if __name__ == "__main__":
    main()