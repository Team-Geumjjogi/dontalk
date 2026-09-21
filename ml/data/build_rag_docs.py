"""qa_flat.jsonl → RAG 문서(jsonl). ★ train split 만 사용합니다 (test 누수 방지).

결과: data/processed/rag_documents.jsonl
  {"doc_id": ..., "text": "...", "metadata": {...}}
"""
import json
from pathlib import Path

from ml.data.parse_aihub import load_cfg

LABELS = {  # text 안에서 보기 좋게 붙일 라벨
    "instruction": "요구사항", "question": "고객 질문", "answer": "상담사 답변",
    "follow_up_question": "꼬리 질문", "output": "종합 답변",
}


def main(config="ml/configs/data.yaml"):
    cfg = load_cfg(config)
    rag = cfg["rag"]
    out_dir = Path(cfg["paths"]["processed_dir"])
    n = 0
    with open(out_dir / "qa_flat.jsonl", encoding="utf-8") as fin, \
         open(out_dir / "rag_documents.jsonl", "w", encoding="utf-8") as fout:
        for line in fin:
            r = json.loads(line)
            if r["split"] != "train":          # ★ valid/test 는 KB 에 넣지 않음
                continue
            text = "\n".join(f"[{LABELS.get(k, k)}] {r[k]}" for k in rag["text_fields"] if r.get(k))
            meta = {k: r.get(k) for k in rag["meta_fields"] + rag["meta_extra"]}
            fout.write(json.dumps({"doc_id": r["qa_id"], "text": text, "metadata": meta},
                                  ensure_ascii=False) + "\n")
            n += 1
    print(f"RAG 문서 {n}건 → {out_dir/'rag_documents.jsonl'}")


if __name__ == "__main__":
    main()
