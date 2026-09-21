"""qa_flat.jsonl → 파인튜닝용 instruction 데이터(jsonl).

sft.mode (ml/configs/data.yaml)
  qa       : input = 고객질문                → output = 상담사 답변(answer)
  followup : input = 고객질문 + 꼬리질문      → output = 최종 답안(output)

결과: data/processed/sft_train.jsonl, sft_valid.jsonl  (test 는 만들지 않음)
TODO(LLM 담당): RAG 검색 결과를 context 로 넣는 버전, 데이터 품질 필터링(output 이 지어낸 정보를 담은 경우 등)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "ai")  # ai/app/llm/prompts.py 를 가져오기 위함 (학습·서빙 프롬프트 통일)
from app.llm.prompts import INSTRUCTION  # noqa: E402

from ml.data.parse_aihub import load_cfg  # noqa: E402


def to_sft(r: dict, mode: str):
    if mode == "qa":
        inp, out = r.get("question"), r.get("answer")
    elif mode == "followup":
        inp = f"{r.get('question','')}\n(추가 질문) {r.get('follow_up_question','')}".strip()
        out = r.get("output")
    else:
        raise ValueError(f"unknown sft.mode: {mode}")
    if not inp or not out:
        return None
    return {"instruction": INSTRUCTION, "input": inp, "output": out,
            "qa_id": r["qa_id"], "category": r.get("category")}


def main(config="ml/configs/data.yaml"):
    cfg = load_cfg(config)
    mode, out_dir = cfg["sft"]["mode"], Path(cfg["paths"]["processed_dir"])
    files = {s: open(out_dir / f"sft_{s}.jsonl", "w", encoding="utf-8") for s in ("train", "valid")}
    counts = {"train": 0, "valid": 0}
    try:
        with open(out_dir / "qa_flat.jsonl", encoding="utf-8") as fin:
            for line in fin:
                r = json.loads(line)
                if r["split"] not in files:    # ★ test 제외
                    continue
                s = to_sft(r, mode)
                if s:
                    files[r["split"]].write(json.dumps(s, ensure_ascii=False) + "\n")
                    counts[r["split"]] += 1
    finally:
        for f in files.values():
            f.close()
    print(f"mode={mode}  {counts}")


if __name__ == "__main__":
    main()
