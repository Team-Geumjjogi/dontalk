# 돈톡 (DonTalk) 💬

> 돈에 대해 편하게 이야기하고, 금융 고민을 톡톡 풀어주는 AI
> Team **금쪽이** (金 + 쪽 + 이 : 금융 정보와 고민을 한 조각씩 쉽게 풀어주는 팀)

금융 RAG 기반 AI 상담 및 상담사 연계 서비스입니다.
은행·보험·증권 상담 데이터로 RAG Knowledge Base를 만들고, 금융 상담 QA로 LLM(EXAONE)을 튜닝해서
근거 기반 답변을 제공하며, 해결되지 않는 문의는 알맞은 상담사에게 연결합니다.

## 이 레포의 성격
**함께 배우는 미니 프로젝트**입니다. 서비스 코드(`web/`, `ai/`, `ml/`)뿐 아니라 각자의 실험 기록(`playground/`, `experiments/`)도 이 레포에 남깁니다.

## 폴더 구조
| 폴더 | 무엇을 | 리뷰 |
|---|---|---|
| `web/` | Flask 웹 서버 (채팅 화면, 로그인, 상담사 이관) | PR 1명 승인 |
| `ai/` | FastAPI AI 서버 (RAG, LLM, 분야 판단) | PR 1명 승인 |
| `ml/` | 데이터 가공, LLM 학습, 평가 스크립트 | PR 1명 승인 |
| `playground/이름/` | **개인 실험실** (노트북, 메모, 시도해본 것 자유롭게) | 필요 없음 |
| `experiments/` | **팀 공식 실험 기록** (`LOG.md`에 한 줄씩) | PR 1명 승인 |
| `docs/` | 데이터 스키마, API 명세, Git/Colab 가이드, 회의록 | PR 1명 승인 |
| `data/` | 데이터 (**Git에 올라가지 않음**) | - |

> 실험(`playground/`)에서 좋은 결과가 나온 코드는 `.py`로 정리해서 `ai/`나 `ml/`로 옮깁니다(승격).

## 처음 시작하기
```bash
git clone https://github.com/Team-geumjjogi/dontalk.git
cd dontalk

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
nbstripout --install                 # 노트북 출력 자동 제거 (1회)
cp .env.example .env                 # 환경변수 파일 만들기
```

## 실행 (mock 모드: 실제 모델 없이 화면/흐름 확인)
터미널 2개가 필요합니다.
```bash
# 터미널 1 - AI 서버
cd ai && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/docs

# 터미널 2 - 웹 서버
cd web && pip install -r requirements.txt
flask --app app run --debug --port 5000          # http://localhost:5000
```
> ⚠ **실행 위치가 중요합니다.** 위 명령은 각각 `ai/`, `web/` 폴더 안에서 실행해야 합니다.

## 데이터 (AI-Hub 「금융분야 고객상담 데이터」)
- 원본은 **Git에 올리지 않습니다.** `data/raw/`에 넣어서 씁니다. 받는 방법과 구조는 [`docs/data-schema.md`](docs/data-schema.md)를 보세요.
- 데이터 가공 실행 (레포 최상위 폴더에서):
```bash
pip install -r ml/requirements.txt
python -m ml.data.parse_aihub --limit 500     # 연습: 파일 500개만
python -m ml.data.parse_aihub                 # 전체
python -m ml.data.build_rag_docs
python -m ml.data.build_sft_dataset
```

## 팀 규칙 (요약)
1. `main`에 직접 작업하지 않습니다. 브랜치를 만들고 Pull Request로 합칩니다. → [`docs/git-guide.md`](docs/git-guide.md)
2. 브랜치 이름: `이름/주제` (예: `eunje/mini-rag`)
3. 데이터·모델 파일·`.env`(비밀키)는 절대 커밋하지 않습니다.
4. 실험을 했다면 성공/실패와 상관없이 `experiments/LOG.md`에 한 줄 남깁니다.
5. Colab은 계정이 1개입니다. → [`docs/colab-guide.md`](docs/colab-guide.md)

## 문서
- [Git 사용 가이드](docs/git-guide.md) · [데이터 스키마](docs/data-schema.md) · [API 명세](docs/api-spec.md) · [Colab 가이드](docs/colab-guide.md)
