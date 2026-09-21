# data/

**이 폴더의 내용물은 Git에 올라가지 않습니다.** (`.gitignore`)

```
data/
├── raw/        # AI-Hub 원본 JSON (라벨링데이터). 각자 내려받아 여기에 둡니다
└── processed/  # 가공 결과 (qa_flat.jsonl, rag_documents.jsonl, sft_*.jsonl, 벡터 인덱스 등)
```
- 다운로드: AI-Hub 「금융분야 고객상담 데이터」 (승인 후 API 다운로드, 분할 압축 파일은 병합 필요)
- 구조 설명: `docs/data-schema.md`
