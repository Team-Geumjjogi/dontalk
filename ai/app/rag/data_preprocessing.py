"""
라벨링 데이터(JSON) DataFrame으로 병합하는 전처리 스크립트

dontalk/
 ├─ ai/app/rag/data_preprocessing.py   ← 이 파일
 └─ data/raw/Training/02.라벨링데이터/01 ~ 09/*.json

실행:
    python data_preprocessing.py
    python data_preprocessing.py --output ../../../data/processed/df_output.xlsx

* data 디렉토리 내 "processed" 디렉토리 새로 생성됨 *
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
    label_dir: Path = field(init=False)
    output_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.label_dir = self.project_root / "data" / "raw" / "Training" / "02.라벨링데이터"
        self.output_path = self.project_root / "data" / "processed" / "df_output.xlsx"


# ----------------------------------------------------------------
# Domain, Class Mapping
# ----------------------------------------------------------------
CATEGORY_MAP: dict[str, dict[str, str]] = {
    "은행": {
        "01": "거래내역/잔액조회",
        "02": "중계요청/착오송금",
        "03": "자동이체조회",
        "04": "만기,연장/해지,수신",
        "05": "금융거래한도/비대면한도계좌",
        "06": "이자/연체금액",
        "07": "부수거래금리감면",
        "08": "대출문의(만기/연장/조회등)",
        "09": "환전문의",
    },
    "보험": {
        "01": "자동차보험상담",
        "02": "자동차사고접수",
        "03": "계약내용변경/해지",
        "04": "기타계약관련문의",
        "05": "보험금청구",
    },
    "증권": {
        "01": "HTS/MTS",
        "02": "계좌관리",
        "03": "신용거래/담보대출",
        "04": "자금이체/계좌제한",
        "05": "절세형금융상품",
        "06": "주식주문",
        "07": "증권계좌조회",
        "08": "해외주문",
    },
}

# Filename-Domain Mapping
DOMAIN_MAP: dict[str, str] = {
    "bk": "은행",
    "ins": "보험",
    "sec": "증권",
}


# ----------------------------------------------------------------
# Preprocessor
# ----------------------------------------------------------------
# Training 디렉토리 내 하위 JSON 파일을 읽어 하나의 DataFrame 생성
class LabelingDataPreprocessor:

    def __init__(
        self,
        config: PathConfig | None = None,
        folder_range: range = range(1, 10),
        category_map: dict[str, dict[str, str]] = CATEGORY_MAP,
        domain_map: dict[str, str] = DOMAIN_MAP,
    ) -> None:
        self.config = config or PathConfig()
        self.folder_range = folder_range
        self.category_map = category_map
        self.domain_map = domain_map


    # ---------------- Dataset Check ----------------
    def _sub_dirs(self) -> list[Path]:
        return [self.config.label_dir / f"{i:02d}" for i in self.folder_range]

    def count_json_files(self) -> int:
        total = 0
        for sub_dir in self._sub_dirs():
            if not sub_dir.exists():
                print(f"[{sub_dir.name}] 디렉토리 없음")
                continue
            count = len(list(sub_dir.glob("*.json")))
            total += count
            print(f"[{sub_dir.name}] {count}개")

        print(f"\n총 json 파일 개수 : {total}개")
        return total


    # ---------------- Filename Parsing ----------------
    def parse_filename(self, filename: str) -> dict[str, str]:
        """예: 'XX_bk_01_....json' → 데이터분야별코드/분류코드/도메인명/중분류코드/중분류명"""
        parts = Path(filename).stem.split("_")
        if len(parts) < 3:
            raise ValueError(f"파일명 형식이 올바르지 않음: {filename}")

        data_field_code, domain_code, middle_code = parts[0], parts[1], parts[2]
        domain_name = self.domain_map.get(domain_code, f"Unknown({domain_code})")
        middle_name = self.category_map.get(domain_name, {}).get(
            middle_code, f"Unknown({middle_code})"
        )

        return {
            "데이터분야별코드": data_field_code,
            "분류코드": domain_code,
            "도메인명": domain_name,
            "중분류코드": middle_code,
            "중분류명": middle_name,
        }


    # ---------------- JSON Flatten ----------------
    @staticmethod
    def flatten_json(data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}

        # source
        for key, value in data.get("source", {}).items():
            result[f"source_{key}"] = value

        # consulting
        for key, value in data.get("consulting", {}).items():
            result[f"consulting_{key}"] = value

        # qa_data (첫 번째 항목만 사용)
        qa_list = data.get("qa_data") or []
        if qa_list:
            for key, value in qa_list[0].items():
                if key == "input" and isinstance(value, dict):
                    for input_key, input_value in value.items():
                        result[f"qa_data_input_{input_key}"] = input_value
                else:
                    result[f"qa_data_{key}"] = value

        return result


    # ---------------- Row / DataFrame ----------------
    def _build_row(self, json_path: Path) -> dict[str, Any]:
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        row: dict[str, Any] = {"파일명": json_path.name}
        row.update(self.parse_filename(json_path.name))
        row["파일경로"] = str(json_path)
        row.update(self.flatten_json(json_data))
        return row


    # 통합 텍스트 컬럼 추가 생성
    @staticmethod
    def add_full_source(df: pd.DataFrame) -> pd.DataFrame:
        columns = {
            "요구사항": "qa_data_instruction",
            "고객질문": "qa_data_input_question",
            "상담사답변": "qa_data_input_answer",
            "꼬리질문": "qa_data_input_follow_up_question",
            "종합답변": "qa_data_output",
        }

        missing = [c for c in columns.values() if c not in df.columns]
        if missing:
            print(f"[WARNING] 누락 컬럼으로 인해 qa_data_full_source 생략: {missing}")
            return df

        df["qa_data_full_source"] = df.apply(
            lambda row: "\n".join(
                f"{label}:{row[col]}" for label, col in columns.items()
            ),
            axis=1,
        )
        return df



    def create_dataframe(self) -> pd.DataFrame:
        all_data: list[dict[str, Any]] = []

        for folder_path in self._sub_dirs():
            if not folder_path.exists():
                print(f"[WARNING] 폴더 없음: {folder_path}")
                continue

            for json_path in sorted(folder_path.glob("*.json")):
                try:
                    all_data.append(self._build_row(json_path))
                except Exception as e:
                    print(f"[ERROR] {json_path}")
                    print(f"       {e}")

        df = pd.DataFrame(all_data)
        if df.empty:
            print("[WARNING] 읽어온 데이터가 없습니다.")
            return df

        df = self.add_full_source(df)
        print(f"DataFrame 생성 완료 (rows={len(df)}, cols={len(df.columns)})")
        return df

    # ---------------- Save / Run ----------------
    def save(self, df: pd.DataFrame, output_path: Path | None = None) -> Path:
        output_path = Path(output_path or self.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)
        print(f"저장 완료: {output_path}")
        return output_path

    def run(self, output_path: Path | None = None) -> pd.DataFrame:
        print(f"라벨링 데이터 경로: {self.config.label_dir}\n")
        if not self.config.label_dir.exists():
            raise FileNotFoundError(f"라벨링 데이터 폴더가 없습니다: {self.config.label_dir}")

        self.count_json_files()
        df = self.create_dataframe()
        if not df.empty:
            self.save(df, output_path)
        return df


# ----------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="라벨링 데이터 JSON → DataFrame(xlsx) 변환")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="저장할 xlsx 경로 (기본:dontalk/data/processed/df_output.xlsx)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preprocessor = LabelingDataPreprocessor()
    preprocessor.run(output_path=args.output)


if __name__ == "__main__":
    main()