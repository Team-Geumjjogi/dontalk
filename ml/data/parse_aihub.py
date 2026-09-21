"""AI-Hub 라벨링 JSON → 한 줄 = QA 1건 인 jsonl 로 펼치기.

사용:
    python -m ml.data.parse_aihub                       # data/raw 아래 전체
    python -m ml.data.parse_aihub --limit 500           # 앞 500개 파일만 (연습용)
    python -m ml.data.parse_aihub --with-content        # 상담 원문(consulting_content)도 포함

결과: data/processed/qa_flat.jsonl
"""
import argparse
import json
from pathlib import Path

import yaml

from ml.data.split import assign_split

CODE_TO_CATEGORY = {"bk": "은행", "ins": "보험", "sec": "증권"}


def load_cfg(path="ml/configs/data.yaml"):
    return yaml.safe_load(open(path, encoding="utf-8"))


def flatten_file(path: Path, seed: int, ratios, with_content: bool):
    """JSON 파일 1개(=상담 1건) → QA 레코드 리스트."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "qa_data" not in data:            # 원천 데이터 등 QA 없는 파일은 건너뜀
        return []
    src, cons = data.get("source", {}), data.get("consulting", {})
    source_id = src.get("source_id", path.stem)
    split = assign_split(source_id, seed, ratios)

    rows = []
    for qa in data["qa_data"]:
        inp = qa.get("input", {})
        row = {
            "source_id": source_id,
            "qa_id": qa.get("qa_id"),
            "split": split,
            "institution": src.get("source_institution"),
            "category": cons.get("consulting_category"),      # 은행/보험/증권
            "consulting_topic": cons.get("consulting_topic"),  # 상담 단위 주제
            "qa_topic": qa.get("qa_topic"),                    # QA 단위 주제
            "consulting_purpose": qa.get("consulting_purpose"),
            "task_category": qa.get("task_category"),
            "consulting_situation": qa.get("consulting_situation"),
            "core_financial_terms": qa.get("core_financial_terms"),
            "consulting_summary": cons.get("consulting_summary"),
            "instruction": qa.get("instruction"),
            "question": inp.get("question"),
            "answer": inp.get("answer"),
            "follow_up_question": inp.get("follow_up_question"),
            "output": qa.get("output"),
        }
        if with_content:
            row["consulting_content"] = src.get("consulting_content")
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="ml/configs/data.yaml")
    ap.add_argument("--limit", type=int, default=None, help="처리할 파일 수 제한")
    ap.add_argument("--with-content", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    ratios = (cfg["split"]["train"], cfg["split"]["valid"], cfg["split"]["test"])
    raw, out_dir = Path(cfg["paths"]["raw_dir"]), Path(cfg["paths"]["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(raw.rglob("*.json"))
    if args.limit:
        files = files[: args.limit]

    n_files = n_rows = n_bad = 0
    with open(out_dir / "qa_flat.jsonl", "w", encoding="utf-8") as f:
        for p in files:
            try:
                rows = flatten_file(p, cfg["seed"], ratios, args.with_content)
            except Exception as e:  # 깨진 파일은 세어두고 계속
                n_bad += 1
                print(f"[skip] {p.name}: {e}")
                continue
            n_files += 1
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n_rows += 1
    print(f"파일 {n_files}개 처리, QA {n_rows}건 저장, 실패 {n_bad}개 → {out_dir/'qa_flat.jsonl'}")


if __name__ == "__main__":
    main()
