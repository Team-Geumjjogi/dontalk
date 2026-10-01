"""
크롤링 데이터(JSON) 표준화 전처리 및 DataFrame으로 병합하는 전처리 스크립트

dontalk/
 ├─ ai/app/rag/data_preprocessing_crawling.py   ← 이 파일
 └─ data/raw/crawling/
      ├─ hana_bk_crawling.json
      ├─ hana_ins_crawling.json
      └─ hana_sec_crawling.json
 
표준화 결과 컬럼:
    instruction, question, answer, consulting_category, consulting_topic
    (총 5개 컬럼)

실행:
    python data_preprocessing_crawling.py
    python data_preprocessing_crawling.py --output ../../../data/processed/df_output_crawling.xlsx
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


# ----------------------------------------------------------------
# Settings (Path etc.)
# ----------------------------------------------------------------
# 가장 상위 디렉토리로 이동 후 실행 위치와 무관하게 해당 파일 기준으로 경로 계산
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class PathConfig:
    
    project_root: Path = PROJECT_ROOT
    crawling_dir: Path = field(init=False)
    output_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.crawling_dir = self.project_root / "data" / "raw" / "crawling"
        self.output_path = self.project_root / "data" / "processed" / "df_output_crawling.xlsx"


# ----------------------------------------------------------------
# Domain, Column Name Mapping
# ----------------------------------------------------------------
# 
FILE_CONFIG: dict[str, dict[str, str]] = {
    "hana_bk_crawling.json":  {"consulting_category": "은행", "topic_key": "consulting_topic"},
    "hana_ins_crawling.json": {"consulting_category": "보험", "topic_key": "category"},
    "hana_sec_crawling.json": {"consulting_category": "증권", "topic_key": "consulting_topic"},
}
 
OUTPUT_COLUMNS: list[str] = [
    "instruction", "question", "answer", "consulting_category", "consulting_topic",
]


# ----------------------------------------------------------------
# Preprocessor
# ----------------------------------------------------------------
# crawling 디렉토리 내 하위 JSON 파일을 읽어 하나의 DataFrame 생성
class CrawlingDataPreprocessor:
 
    def __init__(
        self,
        config: PathConfig | None = None,
        file_config: dict[str, dict[str, str]] = FILE_CONFIG,
    ) -> None:
        self.config = config or PathConfig()
        self.file_config = file_config
 
    # ---------------- Load ----------------
    @staticmethod
    def _load_records(json_path: Path) -> list[dict[str, Any]]:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
 
        if isinstance(data, list):
            return data
 
        if isinstance(data, dict):
            # 흔히 쓰이는 래핑 키들을 순서대로 시도
            for key in ("data", "items", "faqs", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            raise ValueError(
                f"{json_path.name}: 지원하지 않는 JSON 구조입니다. "
                f"최상위가 list이거나 list를 담은 dict여야 합니다. "
                f"(최상위 keys={list(data.keys())})"
            )
 
        raise ValueError(f"{json_path.name}: 알 수 없는 JSON 최상위 타입: {type(data)}")
 
    # ---------------- Row ----------------
    @staticmethod
    def _build_row(
        record: dict[str, Any], consulting_category: str, topic_key: str
    ) -> dict[str, Any]:
        question = record.get("question", "")
        return {
            "instruction": question,          # 현재는 question과 동일하게 사용
            "question": question,
            "answer": record.get("answer", ""),
            "consulting_category": consulting_category,   # 파일명 기준 고정값 (파일 내부 값은 무시)
            "consulting_topic": record.get(topic_key, ""),
        }
 
    # ---------------- DataFrame ----------------
    def create_dataframe(self) -> pd.DataFrame:
        all_rows: list[dict[str, Any]] = []
 
        for filename, cfg in self.file_config.items():
            json_path = self.config.crawling_dir / filename
            if not json_path.exists():
                print(f"[WARNING] 파일 없음: {json_path}")
                continue
 
            records = self._load_records(json_path)
            print(f"[{filename}] {len(records)}건")
 
            for record in records:
                all_rows.append(
                    self._build_row(record, cfg["consulting_category"], cfg["topic_key"])
                )
 
        df = pd.DataFrame(all_rows, columns=OUTPUT_COLUMNS)
        print(f"\nDataFrame 생성 완료 (rows={len(df)}, cols={len(df.columns)})")
        return df
 
    # ---------------- Save / Run ----------------
    def save(self, df: pd.DataFrame, output_path: Path | None = None) -> Path:
        output_path = Path(output_path or self.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)
        print(f"저장 완료: {output_path}")
        return output_path
 
    def run(self, output_path: Path | None = None) -> pd.DataFrame:
        print(f"크롤링 데이터 경로: {self.config.crawling_dir}\n")
        if not self.config.crawling_dir.exists():
            raise FileNotFoundError(f"크롤링 데이터 폴더가 없습니다: {self.config.crawling_dir}")
 
        df = self.create_dataframe()
        if not df.empty:
            self.save(df, output_path)
        return df


# ----------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="크롤링 데이터 JSON → DataFrame(xlsx) 변환")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="저장할 xlsx 경로 (기본: dontalk/data/processed/df_output_crawling.xlsx)",
    )
    return parser.parse_args()
 
 
def main() -> None:
    args = parse_args()
    preprocessor = CrawlingDataPreprocessor()
    preprocessor.run(output_path=args.output)


if __name__ == "__main__":
    main()