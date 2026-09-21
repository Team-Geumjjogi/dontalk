# 데이터 스키마 — AI-Hub 「금융분야 고객상담 데이터」 (초안)

출처: https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&aihubDataSe=data&dataSetSn=71926
(하나은행·하나손해보험·하나증권의 2025년 상담 데이터 기반 / 생성 방식: **LLM** / 다운로드는 AI-Hub 로그인 + 신청 승인 필요, 내국인만 신청 가능)

## 1. 데이터 규모
| 구분 | 은행 | 보험 | 증권 | 합계 |
|---|---|---|---|---|
| 원천데이터(상담) | 32,998 | 22,485 | 15,774 | 71,257 |
| **라벨링데이터(QA)** ← 우리가 사용 | 50,000 | 30,000 | 20,000 | **100,000** |

상담 1건에서 QA가 1개 이상 나옵니다. (파일 하나 = 상담 1건 = `qa_data` 리스트)

## 2. 파일명 / ID 규칙
`21-1_{bk|ins|sec}_{주제번호}_{일련번호}_{연번}.json` 예) `21-1_ins_01_000009_001.json`
- `bk`=은행, `ins`=보험, `sec`=증권
- `source_id` = 상담 ID (`21-1_ins_01_000009`), `qa_id` = QA ID (`…_001`)

## 3. 주요 필드 (라벨링 JSON)
| 위치 | 필드 | 설명 |
|---|---|---|
| `source` | `source_institution`, `source_id`, `source_date`, `client_gender/age`, `consulting_content`(상담 원문) | |
| `consulting` | `consulting_category` | **은행 / 보험 / 증권** (Routing 정답 라벨) |
| | `consulting_topic` | 상담 주제 (아래 목록) |
| | `consulting_summary` | 상담 요약 |
| `qa_data[]` | `qa_id`, `task_category`(일반상담/핵심금융용어), `consulting_situation`(일반 문의/업무처리/민원 응대) | |
| | `qa_topic`, `consulting_purpose`(예: "마일리지 환급 안내"), `core_financial_terms` | |
| | `instruction` | 지시문 (= 회의안의 "요구사항") |
| | `input.question` / `input.answer` / `input.follow_up_question` | 고객 질문 / 상담사 답변 / 꼬리 질문 |
| | `output` | 모범답변 (= 회의안의 "종합 답변/최종 답안") |

## 4. 상담 주제(consulting_topic) 목록
- **은행(9)**: 거래내역/잔액조회, 중계요청/착오송금, 자동이체조회, 만기,연장/해지,수신, 금융거래한도/비대면한도계좌, 이자/연체금액, 부수거래금리감면, 대출문의(만기/연장/조회등), 환전문의
- **보험(5)**: 자동차보험상담, 자동차사고접수, 계약내용변경/해지, 기타계약관련문의, 보험금청구/확인 (코드표에는 "보험금청구"로 표기됨)
- **증권(8)**: HTS/MTS, 계좌관리, 신용거래/담보대출, 자금이체/계좌제한, 절세형금융상품, 주식주문, 증권계좌조회, 해외주문

## 5. 우리가 만드는 가공 파일 (`data/processed/`, Git 제외)
| 파일 | 내용 | 만드는 스크립트 |
|---|---|---|
| `qa_flat.jsonl` | QA 1건 = 1줄로 펼친 표. `split`(train/valid/test) 포함 | `ml/data/parse_aihub.py` |
| `rag_documents.jsonl` | RAG용 `{doc_id, text, metadata}`. **train만** | `ml/data/build_rag_docs.py` |
| `sft_train.jsonl`, `sft_valid.jsonl` | 파인튜닝용 `{instruction, input, output}`. **test 제외** | `ml/data/build_sft_dataset.py` |

## 6. 분할(split) 규칙 ★ 가장 먼저 지킬 것
- **상담(`source_id`) 단위**로 train 80 / valid 10 / test 10 (seed=42, 해시 기반이라 모두 같은 결과)
- test 는 RAG Knowledge Base 와 LLM 학습에 **절대 사용하지 않음** (평가 누수 방지)

## 7. 데이터 관련 주의점 (EDA에서 눈으로 확인할 것)
1. **라벨링 데이터는 LLM이 생성**했습니다. `output`에 상담 원문에 없는 내용이 들어갈 수 있습니다. (샘플: 원문에 없는 "필요 서류 목록"이 `output`에 등장) → 그대로 학습하면 지어내기를 배울 수 있으니 품질 확인 필요.
2. `consulting_content`(상담 원문)는 마스킹(●)과 어색한 문장이 섞여 있어 RAG 텍스트로 쓸지 신중히 판단.
3. 주제명이 문서마다 조금 다를 수 있음(예: `보험금청구` vs `보험금청구/확인`) → 실제 값을 집계해서 표준화.
4. 한 상담의 QA가 여러 개일 수 있음 → split 은 반드시 `source_id` 기준.

## 8. 회의에서 아직 미결인 것 (→ `ml/configs/data.yaml` 스위치로 실험)
- [ ] 메타데이터: 4개(`category, consulting_topic, qa_topic, consulting_purpose`)를 그대로 vs 2개로 조합
- [ ] RAG text 에 어떤 필드를 넣을지 (요구사항 / 질문 / 답변 / 꼬리질문 / 종합답변)
- [ ] SFT: 고객질문→상담사답변(`qa`) vs 고객질문+꼬리질문→최종답안(`followup`)
- [ ] SFT 입력에 RAG 검색 결과(context)를 포함할지
- [ ] 유사도가 낮을 때 상담사 이관 기준(threshold)
