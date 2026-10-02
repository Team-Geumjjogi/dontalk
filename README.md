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
| `web/` | Flask 웹 서버 (고객 채팅, 상담사/관리자 화면) | PR 1명 승인 |
| `ai/` | FastAPI AI 서버 (RAG 검색, LLM, 분야 판단, 이관 판단) | PR 1명 승인 |
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

uv sync                              # 의존성 설치 (루트 pyproject.toml/uv.lock 하나로 통합. 각자 uv init 금지)
uv run nbstripout --install          # 노트북 출력 자동 제거 (1회)
cp .env.example .env                 # 환경변수 파일 만들기 → DB_* 등 값은 팀원에게 받아서 채우기
```

## 실행
서비스는 **서버 3개**입니다 (각각 별도 터미널, 아래 순서대로). `.env`에 공용 DB 접속 정보(`DB_*`)가 필요합니다.
```bash
# 1) Ollama (LLM) - 앱을 켜 두고, 모델이 있는지 확인. 없으면 `ollama pull exaone3.5:2.4b`
ollama list

# 2) AI 서버 (RAG 검색 + LLM). .env 의 AI_MOCK_MODE=false 여야 실제 모델을 씁니다. 시작 후 20~30초는 워밍업.
cd ai && uv run uvicorn app.main:app --port 8000
curl localhost:8000/health                       # {"status":"ok","mock_mode":false}

# 3) 웹 서버
cd web && uv run flask --app app run --debug --port 5001     # http://localhost:5001
```
- `AI_MOCK_MODE=true` 로 두면 모델/DB 없이 가짜 응답으로 화면만 확인할 수 있습니다 (1, 2번 없이도 웹 개발 가능).
- 웹 로그인 계정(상담사/관리자)은 회원가입이 없고 CLI로 만듭니다: `cd web && flask --app app create-employee --name 김서연 --email agent1@dontalk.com --password test1234 --role agent --department 은행` (관리자는 `--role admin`, `--department` 생략).
- 웹 DB 테이블 구조를 바꿨다면 `cd web && flask --app app reset-db --yes` (웹 전용 테이블만 재생성, 지식베이스는 그대로). 구조는 [`docs/web-db-schema.md`](docs/web-db-schema.md).
- 테스트: `cd web && uv run python -m pytest -q` , `cd ai && uv run python -m pytest -q`
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
2. 브랜치 이름: `주제/이름` (예: `mini-rag/eunje`)
3. 데이터·모델 파일·`.env`(비밀키)는 절대 커밋하지 않습니다.
4. 실험을 했다면 성공/실패와 상관없이 `experiments/LOG.md`에 한 줄 남깁니다.
5. Colab은 계정이 1개입니다. → [`docs/colab-guide.md`](docs/colab-guide.md)

## 문서
- [Git 사용 가이드](docs/git-guide.md) · [데이터 스키마](docs/data-schema.md) · [API 명세](docs/api-spec.md) · [웹 DB 스키마](docs/web-db-schema.md) · [Colab 가이드](docs/colab-guide.md)
