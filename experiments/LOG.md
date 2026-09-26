# 실험 기록

실험을 했다면 **성공/실패와 상관없이** 표에 한 줄 추가하세요. 실패한 실험도 발표의 "실패 사례 분석" 재료가 됩니다.
자세한 내용이 필요하면 `TEMPLATE.md`를 복사해서 `experiments/YYYY-MM-DD_이름_주제.md`로 만들고 아래 표에 링크합니다.

| 날짜 | 담당 | 실험 | 바꾼 변수 | 결과 (지표) | 한 줄 결론 | 상세 |
|---|---|---|---|---|---|---|
| 예) 09-24 | 예시 | 미니 RAG | 임베딩 모델 A vs B | Hit@3 0.71 / 0.78 | B가 금융 용어에 강함 | (링크) |
| 09-26 | 김영빈 | RAG 임베딩+검색 baseline (dragonkue/snowflake-arctic-embed-l-v2.0-ko + pgvector, TL 8만 건 적재, VL 500건 평가) | - (첫 baseline) | Hit@5 0.878(strict)/0.986(loose), MRR 0.763/0.945, 검색속도 평균 25.1ms | 전반적으로 준수하나 증권 카테고리가 가장 약함(Hit@5 0.792) | [playground/youngbeen/eval_retrieval.ipynb](../playground/youngbeen/eval_retrieval.ipynb) |
