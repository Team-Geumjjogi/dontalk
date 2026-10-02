# GPU 서버 배포 가이드 (vLLM + AI API)

GPU 서버(RTX 3060, WSL2 Ubuntu)에서 vLLM(모델 + LoRA 어댑터)과 AI API(FastAPI)를 `docker-compose.server.yml`로 띄우는 절차입니다.
이 문서의 명령은 서버에서 실행합니다. 아직 서버에서 실제로 실행해 보지 않은 항목은 **(미검증)** 으로 표시했습니다.

## 1. 구성

```
웹(Flask) ──HTTP──▶ api (FastAPI, dontalk-ai)  ──compose 내부망──▶ vllm (dontalk-vllm)
                      │                                              ├─ base: exaone (EXAONE-3.5-2.4B)
                      └─ 공용 DB (RAG 검색, 읽기 전용)                  └─ LoRA: bank / insurance / securities
```

| 서비스 | 컨테이너 | 하는 일 | 호스트 포트 |
|---|---|---|---|
| `vllm` | `dontalk-vllm` | 모델 + 어댑터 3종을 OpenAI 호환 API로 서빙 | `127.0.0.1:8001` (서버 로컬에서만) |
| `api` | `dontalk-ai` | RAG 검색 → 분야 판단 → vLLM 호출 → 답변 정리/이관 판단 | `AI_BIND:8000` (기본 `127.0.0.1`) |

- api는 `http://vllm:8000/v1`(compose 내부망)로 vLLM에 접근합니다. 그래서 vLLM 호스트 포트는 디버깅용 `curl`에만 쓰입니다.
- 분야(은행/보험/증권)에 따라 요청의 `model` 필드로 어댑터(`bank`/`insurance`/`securities`)를 고릅니다.
- 시스템 프롬프트는 어댑터 학습 때와 같은 문구(`ai/app/llm/prompts.py`)여야 해서 임의로 바꾸면 안 됩니다.

## 2. 서버의 기존 상태 (2026-10-02 확인)

`sudo docker ps` 결과, 새 compose가 아닌 예전에 수동으로 띄운 컨테이너가 돌고 있었습니다.

| 컨테이너 | 이미지 | 비고 |
|---|---|---|
| `dontalk-ai` | `dontalk-ai` (수동 빌드) | 약 14시간 전 생성. 이번 전환 코드(vLLM 연결, `handoff_reason`, 의존성)가 반영되지 않은 버전 |
| `exaone-vllm` | `vllm/vllm-openai:latest` | 약 15시간 전 생성. 명령 `vllm serve /models/…`. 포트 `0.0.0.0:8001`로 **외부에 노출됨** |

- 작업 폴더는 `~/server_ai`, docker는 `sudo`로 실행합니다.
- 새 compose를 그대로 `up` 하면 **컨테이너 이름(`dontalk-ai`)과 포트(8000, 8001)가 충돌**해서 실패합니다. 아래 5장의 교체 절차가 필요합니다.

## 3. 사전 준비

### 3-1. 코드를 서버로 가져오기

서버의 작업 폴더(`~/server_ai` 또는 새 폴더)에 아래가 있어야 합니다.

```
docker-compose.server.yml
.env.server.example
ai/            # Dockerfile, requirements.txt, app/
```

저장소를 clone하거나 pull하세요. 폴더가 `/mnt/c/...`(Windows 디스크) 아래이면 파일 I/O가 매우 느리므로 WSL의 ext4(`/home/...`)에 두세요.

### 3-2. 모델·어댑터 폴더

`.env.server`의 `MODELS_DIR`, `ADAPTERS_DIR`가 가리키는 폴더 구조가 compose와 같아야 합니다. 모델과 어댑터 파일은 Git에 없습니다.

```
$MODELS_DIR/
├── exaone-3.5-2.4b/     # EXAONE-3.5-2.4B-Instruct 가중치  (compose: --model /models/exaone-3.5-2.4b)
└── tokenizer/           # 토크나이저                        (compose: --tokenizer /models/tokenizer)

$ADAPTERS_DIR/
├── bank/                # adapter_config.json, adapter_model.safetensors
├── insurance/
└── securities/
```

> (미검증) 위 폴더 구조는 "models 안에 exaone-3.5-2.4b, tokenizer, adapters가 있다"는 전달 내용과 compose의 현재 경로를 바탕으로 한 것입니다. 실제 구조는 5장의 백업 명령(`inspect`, `ls`)으로 확인하고, 다르면 compose의 `--model`, `--tokenizer`, `volumes`를 맞추세요.

확인할 것:
- 어댑터의 `adapter_config.json`의 `r`이 `VLLM_MAX_LORA_RANK`(16) 이하여야 합니다. (현재 r=16 확인됨)
- DB의 `consulting_category`는 `은행`/`보험`/`증권` 3가지입니다. 이 값이 `ADAPTER_NAMES`(`ai/app/llm/vllm_client.py`)와 정확히 같아야 어댑터가 선택됩니다.

### 3-3. `.env.server` 만들기

`.env.server`는 저장소에 없습니다(`.gitignore`로 제외). 서버에서 예시 파일을 복사해 값을 채웁니다.

```bash
cp .env.server.example .env.server
nano .env.server
```

| 변수 | 설명 | 예시/기본 |
|---|---|---|
| `MODELS_DIR` | 모델 폴더의 **절대경로** (WSL ext4) | `/home/cwc/dontalk/models` |
| `ADAPTERS_DIR` | 어댑터 폴더의 절대경로 | `/home/cwc/dontalk/adapters` |
| `VLLM_PORT` | vLLM 호스트 포트 (로컬 바인딩) | `8001` |
| `VLLM_MAX_MODEL_LEN` | 최대 컨텍스트 길이. 토큰 실측 후 결정 (9장) | `4096` |
| `VLLM_GPU_UTIL` | GPU 메모리 사용 비율 | `0.85` |
| `VLLM_MAX_LORA_RANK` | 어댑터 rank 이상이어야 함 | `16` |
| `AI_PORT` | api 호스트 포트 | `8000` |
| `AI_BIND` | api 포트를 열 호스트 주소 (7장) | `127.0.0.1` |
| `AI_MOCK_MODE` | `false` = 실제 vLLM 호출, `true` = 가짜 응답 | `false` |
| `VLLM_BASE_URL` | compose 내부 주소(서비스명 + 컨테이너 포트) | `http://vllm:8000/v1` |
| `VLLM_TIMEOUT` | LLM 호출 타임아웃(초). 브라우저 90 > 웹→AI 70 > AI(검색 ~22 + LLM 40) | `40` |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | RAG 공용 DB 접속 정보 (필수) | 팀원에게 받은 값 |
| `DB_SSLMODE`, `DB_SSLNEGOTIATION` | DB SSL 설정 | `require`, `direct` |
| `EMBEDDING_MODEL` | 비우면 기본 임베딩 모델 사용 | (빈 값) |

- `VLLM_BASE_URL`에 호스트 포트(8001)를 넣지 마세요. compose 내부에서는 컨테이너 포트(8000)를 씁니다.
- DB 5개 값은 비어 있으면 compose가 시작 전에 에러로 알려 줍니다(`required variable ... is missing a value`).
- 비밀번호가 들어 있으므로 `.env.server`를 채팅·이슈·커밋에 붙여 넣지 마세요.

### 3-4. 개발 PC에서 사전 검증 (서버에 올리기 전)

api 이미지는 **서버에서 빌드**합니다(5장). 개발 PC에서 이미지를 만들어 서버로 전송하는 방식은 쓰지 않습니다. 전송해도 compose 파일·`.env.server`는 따로 옮겨야 하고, 어느 커밋으로 만든 이미지인지 추적이 어려우며, 임베딩 모델은 서버가 첫 시작 때 인터넷에서 내려받기 때문입니다. 대신 서버로 가져가기 전에 아래 중 가능한 검증을 개발 PC에서 해 둡니다.

**A. Docker가 되는 PC: 이미지 빌드와 import 확인**

```bash
docker build -t dontalk-ai-test ./ai
docker run --rm -e DB_HOST=h -e DB_PORT=1 -e DB_USER=u -e DB_PASSWORD=p -e DB_NAME=n \
  dontalk-ai-test python -c "import app.main, app.rag.retriever; print('import ok')"
```

**B. Docker가 안 되는 PC: `requirements.txt`만으로 앱이 import되는지 확인**

Dockerfile이 하는 일(CPU 전용 torch 먼저 설치 → `requirements.txt` 설치)을 깨끗한 가상환경에서 그대로 흉내 냅니다. 이 확인은 `requirements.txt`에서 빠진 패키지가 있는지 잡아냅니다. 루트의 `.venv`에는 모든 패키지가 깔려 있어서 `pytest`가 통과해도 이 누락은 드러나지 않습니다.

```bash
# 저장소 루트(dontalk/)에서. Windows는 python 경로가 Scripts\python.exe, Linux/macOS는 bin/python
uv venv --python 3.12 /tmp/cleanvenv
uv pip install --python /tmp/cleanvenv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python /tmp/cleanvenv/bin/python -r ai/requirements.txt

# 커밋된 상태 그대로 확인하려면 HEAD를 따로 풀어서 실행
mkdir /tmp/snap && git archive HEAD | tar -x -C /tmp/snap && cd /tmp/snap/ai
AI_MOCK_MODE=false DB_HOST=h DB_PORT=1 DB_USER=u DB_PASSWORD=p DB_NAME=n \
  /tmp/cleanvenv/bin/python -c "import app.main, app.rag.retriever, app.llm.vllm_client, app.services.chat_service; print('imports OK')"

# Linux·Python 3.12 기준으로 의존성이 해석되는지 (설치 없이)
uv pip compile ai/requirements.txt --python-platform x86_64-manylinux_2_28 --python-version 3.12 --quiet | head
```

**실행 결과 (2026-10-02, Windows 개발 PC, 커밋 `f5dedde` 기준)**

| 확인 | 결과 |
|---|---|
| Linux·Python 3.12 의존성 해석 | 성공 (psycopg 3.3.6, pgvector 0.5.0, sentence-transformers 6.1.0) |
| CPU torch를 먼저 설치한 뒤 `requirements.txt` 설치 | torch가 `2.14.1+cpu`로 유지됨. CUDA 빌드로 교체되지 않음 |
| `app.main`, `app.rag.retriever`, `app.llm.vllm_client`, `app.services.chat_service` import | 성공 |

**이 검증으로 알 수 없는 것**
- `Dockerfile` 자체의 빌드 성공 여부(`COPY`, `CMD`, Linux 휠 설치). 서버에서 처음 `up --build` 할 때 확인합니다.
- 임베딩 모델의 HuggingFace 다운로드와 로드, 공용 DB 접속.
- 설치된 `transformers`가 5.18.0이라 팀의 `uv.lock`(5.8.1, `pyproject.toml`은 `<5.9`)과 다릅니다. import는 성공했지만 임베딩 모델 로드는 확인하지 않았습니다. 서버에서 `워밍업 실패`가 나오면 `requirements.txt`에 `transformers>=4.56,<5.9`를 추가해 `pyproject.toml`과 맞추세요.

## 4. 명령 편의 (alias)

compose 파일 이름이 기본값(`docker-compose.yml`)이 아니라서 옵션이 매번 필요합니다. 폴더에는 로컬 개발용 `docker-compose.yml`도 있어서, 옵션 없이 실행하면 **다른 파일이 실행됩니다.**

```bash
alias dcs='sudo docker compose -f docker-compose.server.yml --env-file .env.server'
```

이 문서의 이후 명령은 `dcs`를 씁니다. 새 셸에서는 alias를 다시 만들어야 합니다(`~/.bashrc`에 추가하면 유지).

## 5. 기존 컨테이너를 새 compose로 교체

> 교체하는 동안 챗봇 AI 응답이 잠시 끊깁니다. 사용 중이 아닐 때 진행하세요.

### 5-1. 기존 설정 백업 (삭제하기 전에 반드시)

동작하던 vLLM의 실행 인자와 마운트는 모델 경로·LoRA 옵션의 정답입니다. 삭제 전에 저장하세요.

```bash
mkdir -p ~/server_ai/backup

# vLLM 실행 인자 (--model / --tokenizer / --lora-modules 등)
sudo docker inspect exaone-vllm --format '{{range .Config.Cmd}}{{.}} {{end}}' | tee ~/server_ai/backup/exaone-vllm-cmd.txt

# 마운트 (호스트 폴더 -> 컨테이너 폴더)
sudo docker inspect exaone-vllm --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' | tee ~/server_ai/backup/exaone-vllm-mounts.txt

# 현재 노출된 모델 목록
curl -s localhost:8001/v1/models | tee ~/server_ai/backup/models.json

# 폴더 구조
ls -R "$MODELS_DIR" "$ADAPTERS_DIR" | head -60   # .env.server의 값 또는 위 마운트의 Source 경로
```

- `dontalk-ai`의 환경변수(`docker inspect`의 `Config.Env`)에는 DB 비밀번호가 들어 있습니다. 확인할 때는 `... | grep -v PASSWORD`로 걸러서 보고, 파일로 저장하거나 공유하지 마세요.
- 백업한 `exaone-vllm-cmd.txt`의 `--model`, `--tokenizer`, `--lora-modules`가 `docker-compose.server.yml`의 `vllm.command`와 같은지 비교하고, 다르면 compose를 고치세요.

### 5-2. 교체

```bash
cd ~/server_ai                      # docker-compose.server.yml이 있는 폴더

# 기존 컨테이너 중지 (이미지는 롤백용으로 지우지 않습니다)
sudo docker stop dontalk-ai exaone-vllm
sudo docker rename dontalk-ai dontalk-ai-old        # 이름 충돌 방지 + 되돌리기용
sudo docker rename exaone-vllm exaone-vllm-old

# 설정 검증 (필수 값이 비어 있으면 여기서 실패)
dcs config -q

# 실행 (api 이미지는 처음에 빌드됨. CPU torch + sentence-transformers 설치로 시간이 걸립니다)
dcs up -d --build
dcs ps
```

- 중지·이름 변경만 하고 컨테이너는 지우지 않으므로 롤백이 쉽습니다(8장). 새 구성이 안정되면 `sudo docker rm dontalk-ai-old exaone-vllm-old`로 정리하세요.
- 첫 기동은 vLLM이 모델과 LoRA를 올리는 데 시간이 걸립니다. healthcheck의 `start_period`는 180초이며, `retries: 10`(30초 간격)까지 기다립니다.

## 6. 검증 체크리스트

위에서부터 순서대로 확인합니다. 앞 단계가 실패하면 뒤 단계는 의미가 없습니다.

| # | 확인 | 명령 | 기대 결과 |
|---|---|---|---|
| 1 | vLLM 기동 | `dcs logs -f vllm` | 에러 없이 `Application startup complete`. LoRA 3개(bank, insurance, securities) 로드 메시지 |
| 2 | vLLM 상태 | `dcs ps` | `dontalk-vllm`이 `healthy` |
| 3 | 모델 목록 | `curl -s localhost:8001/v1/models` | `exaone`, `bank`, `insurance`, `securities` |
| 4 | api 기동 | `dcs logs api` | `워밍업 완료`. 실패 시 DB 접속 정보 또는 임베딩 모델 다운로드(인터넷 필요) 문제 |
| 5 | api 상태 | `curl -s localhost:8000/health` | 정상 응답 |
| 6 | 어댑터 직접 호출 | 아래 `curl` | 한국어 답변 |
| 7 | 전체 흐름 | 웹 또는 `hurll`로 `/chat` 호출 | 분야별 질문 1개씩에서 근거 기반 답변 |
| 8 | 장애 시 동작 | `dcs stop vllm` 후 `/chat` 호출 | 상담사 이관 응답 + `handoff_reason`에 `LLM 오류: ConnectError: ...`. 확인 후 `dcs start vllm` |
| 9 | 외부 비노출 | 다른 PC에서 `curl <서버IP>:8001`, `:8000` | 연결 거부 (7장) |

6번 직접 호출 예시(어댑터 이름을 `model`에 넣습니다):

```bash
curl -s localhost:8001/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "bank",
  "messages": [{"role": "user", "content": "고객 질문 : 대출 만기 연장은 어떻게 하나요?\nRAG 결과: "}],
  "max_tokens": 128
}'
```

> (미검증) EXAONE 3.5 + LoRA 조합이 현재 `vllm/vllm-openai:latest` 버전에서 로드되는지, healthcheck의 `curl`이 이미지에 있는지는 서버에서 처음 `up` 할 때 확인해야 합니다. 동작이 확인되면 `latest`를 확인된 버전 태그로 고정하세요.

## 7. 포트와 외부 노출

두 서비스 모두 기본값이 **로컬 바인딩**입니다(`docker compose config`로 `host_ip: 127.0.0.1` 확인).

| 포트 | 설정 | 의미 |
|---|---|---|
| vLLM 8001 | `127.0.0.1:${VLLM_PORT}:8000` 고정 | 서버 로컬에서만 접근. vLLM에는 인증이 없으므로 외부에 열면 안 됩니다 |
| api 8000 | `${AI_BIND:-127.0.0.1}:${AI_PORT}:8000` | 기본은 서버 로컬 전용 |

### 웹 서버가 어디에 있느냐에 따라

| 웹 위치 | `AI_BIND` | 웹의 `AI_SERVER_URL` |
|---|---|---|
| 같은 서버 | `127.0.0.1` (기본) | `http://localhost:8000` |
| 다른 PC (사설망/VPN) | 이 서버의 **사설 IP** (예: `192.168.0.10`) | `http://<사설IP>:8000` |
| 다른 PC (SSH 터널) | `127.0.0.1` (기본) | 웹 쪽에서 `ssh -L 8000:localhost:8000 <서버>` 후 `http://localhost:8000` |

- `AI_BIND=0.0.0.0`은 공용 인터페이스에서 쓰지 마세요. 인터넷에서 `/chat`을 누구나 호출하게 됩니다.
- 바인딩을 바꾼 뒤에는 `dcs up -d`로 컨테이너를 다시 만들어야 적용됩니다.

### ufw만으로는 막히지 않습니다

Docker가 게시한 포트는 `ufw` 규칙을 우회합니다(Docker가 iptables를 직접 수정하기 때문). 즉 `0.0.0.0`으로 게시된 포트는 `ufw deny`를 해도 열려 있을 수 있습니다. 그래서 이 구성은 방화벽에 의존하지 않고 **게시 주소 자체를 `127.0.0.1`로 제한**합니다. 기존 `exaone-vllm`(`0.0.0.0:8001`)이 바로 이 경우였습니다.

### 확인

```bash
sudo ss -ltnp | grep -E ':8000|:8001'     # 127.0.0.1:8000 / 127.0.0.1:8001 로 보여야 함 (0.0.0.0이면 안 됨)
sudo docker ps --format '{{.Names}}\t{{.Ports}}'
```

## 8. 롤백 (새 구성이 안 될 때)

5-2에서 기존 컨테이너를 지우지 않고 이름만 바꿨다면 되돌릴 수 있습니다.

```bash
dcs down                                          # 새 구성 중지/삭제 (hf-cache 볼륨은 유지)
sudo docker rename dontalk-ai-old dontalk-ai
sudo docker rename exaone-vllm-old exaone-vllm
sudo docker start exaone-vllm dontalk-ai
```

- 기존 컨테이너는 외부 노출(`0.0.0.0:8001`) 상태로 되돌아갑니다. 임시로만 쓰고 원인을 찾아 새 구성으로 다시 시도하세요.
- 5-1에서 백업한 `exaone-vllm-cmd.txt`로 같은 인자의 컨테이너를 다시 만들 수도 있습니다.

## 9. 컨텍스트 길이(`VLLM_MAX_MODEL_LEN`) 정하기

기본값은 4096입니다. 기존 로컬(ollama)은 8192였고, vLLM은 서버 시작 옵션이라 요청별로 바꿀 수 없습니다. 프롬프트가 한도를 넘으면 vLLM이 400을 내고, api는 상담사 이관으로 처리합니다. 이제 `handoff_reason`에 오류 메시지가 남으므로 증상은 `LLM 오류: HTTPStatusError: Client error '400 Bad Request' ...`처럼 보입니다.

필요한 길이 = **최대 프롬프트 토큰 + `max_tokens`(512) + 여유 약 10%**.

실측 방법:
1. 실제 질문 20~30개(후속 질문 포함)를 `/chat`으로 보내 vLLM 로그(`dcs logs vllm`)에서 요청별 prompt 토큰 수를 확인하거나, vLLM 응답의 `usage.prompt_tokens`를 본다.
2. 최대값에 512와 여유를 더한 값이 4096을 넘으면 `.env.server`의 `VLLM_MAX_MODEL_LEN`을 올리고 `dcs up -d`로 재시작한다.
3. 올려도 되는지는 vLLM 시작 로그의 KV cache 크기로 확인한다. 2.4B 모델은 토큰당 KV 캐시가 작아(추정 약 77KB) 8192여도 3060 12GB에서 큰 부담이 아닐 것으로 보이지만, **실제 값은 로그로 확인**하세요.
4. 올릴 수 없거나 올릴 필요가 없다면 `chat_service`에서 vLLM에 넘기는 RAG 문서 개수·길이를 제한합니다.

## 10. 문제 해결

| 증상 | 원인 후보 | 조치 |
|---|---|---|
| `up` 시 `container name ... already in use` | 기존 `dontalk-ai`/`exaone-vllm`이 남아 있음 | 5-2의 stop + rename |
| `up` 시 `port is already allocated` | 기존 컨테이너가 8000/8001 사용 중 | 5-2의 stop |
| `required variable ... is missing a value` | `.env.server`의 DB 값 또는 경로 누락 | 3-3 표 확인 |
| `docker compose` 실행 시 엉뚱한 서비스가 뜸 | `-f docker-compose.server.yml` 없이 실행해 로컬용 compose가 사용됨 | `dcs` alias 사용 |
| vllm이 바로 종료 | 모델/토크나이저 경로 오타, GPU 메모리 부족, LoRA 로드 실패 | `dcs logs vllm` 마지막 30줄. `--model`/`--tokenizer`/`--lora-modules` 경로와 `VLLM_GPU_UTIL` 확인 |
| vllm이 계속 `unhealthy` | 아직 로딩 중이거나 healthcheck의 `curl`이 이미지에 없음 | 로그에서 `startup complete` 확인. 로그는 정상인데 unhealthy면 healthcheck 방식을 바꿔야 함 |
| api가 시작되지 않음 | vllm이 healthy가 아님(`depends_on`) | 위 vllm 항목 먼저 해결 |
| api 로그에 `워밍업 실패` | DB 접속 정보 오류, 방화벽, 임베딩 모델 다운로드 실패(인터넷) | 로그 상세 확인. DB는 `DB_*`, 임베딩은 서버의 외부 접속 가능 여부 |
| 모든 응답이 상담사 이관 | vLLM 연결 실패, 분야명 불일치, 컨텍스트 초과 | 응답의 `handoff_reason` 확인 (`LLM 오류: ...`) 후 `dcs logs api` |
| `ValueError: 지원하지 않는 분야` | DB 분야명이 `은행/보험/증권`과 다름 | DB 값 확인 후 `ADAPTER_NAMES` 맞추기 |
| `permission denied` (docker) | docker 그룹 미가입 | `sudo` 사용 |
| (개발 PC) Docker Desktop을 켜도 `docker info`가 `500 Internal Server Error` | 로그에 "가상화가 활성화되지 않은 이 컴퓨터에서는 WSL2를 시작할 수 없습니다" → BIOS의 가상화(VT-x/SVM)가 꺼져 있거나 Windows의 '가상 머신 플랫폼'이 비활성 | BIOS에서 가상화를 켜고 `wsl --install --no-distribution` 후 재부팅. 어렵다면 3-4장의 B 방법으로 대체 검증하고 이미지 빌드는 서버에서 |

## 11. 운영 명령 모음

```bash
dcs ps                          # 상태
dcs logs -f api                 # api 로그
dcs logs -f vllm                # vLLM 로그
dcs restart api                 # api만 재시작
dcs up -d --build api           # 코드 변경 후 api 이미지 다시 빌드
dcs down                        # 전체 중지/삭제 (hf-cache 볼륨은 유지)
dcs down -v                     # 볼륨까지 삭제 (임베딩 모델 캐시도 삭제되어 다음 기동 때 다시 내려받음)
sudo docker system df           # 디스크 사용량
```

- 코드를 바꾼 뒤에는 서버에서 `git pull` → `dcs up -d --build api`.
- api 재시작 때마다 임베딩 모델을 다시 내려받지 않는 것은 `hf-cache` 볼륨 덕분입니다.

## 12. 아직 확인되지 않은 것

- 서버 `models/` 폴더의 실제 구조와 compose 경로 일치 여부
- EXAONE 3.5 + LoRA 조합의 vLLM 로드, healthcheck의 `curl` 존재 여부
- api 이미지 빌드 — 개발 PC에서는 가상화가 꺼져 있어 Docker 엔진이 시작되지 않아 빌드하지 못했습니다. 대신 3-4장 B 방법으로 `requirements.txt`의 의존성과 import는 확인했고(성공), Dockerfile 빌드와 Linux 휠 설치는 서버의 첫 빌드에서 확인합니다.
- 다중턴(이전 대화를 프롬프트에 포함) 후속 질문의 실제 답변 품질
- `VLLM_MAX_MODEL_LEN` 적정값 (9장 실측)
