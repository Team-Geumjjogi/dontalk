# LLM 실행 환경

Python 3.12 이상에서 저장소 루트의 `uv sync --locked`로 설치합니다.
패키지 선언은 `pyproject.toml`, 재현 가능한 설치 버전은 `uv.lock`으로 관리합니다.
PyTorch가 지원하는 Windows/Linux/macOS에서 CPU 실행이 기본 호환 경로입니다.
프로젝트 루트의 `.env`에 설정한 뒤 `ai/`에서 실행합니다.

```dotenv
LLM_DEVICE=auto
LLM_LOAD_IN_4BIT=false
LLM_ADAPTER_ROOT=
```

- `auto`: CUDA가 있으면 FP16, 없으면 CPU FP32. CPU에는 bitsandbytes가 필요 없습니다.
- `cpu`: GPU가 있어도 CPU 사용. FP32 기본 가중치만 약 9.6GB이며, 실행에는 추가 메모리가 필요합니다.
- `cuda`: CUDA 사용을 강제합니다. 해당 드라이버와 호환되는 PyTorch를 설치해야 합니다.
- `mps`: Apple GPU를 명시적으로 선택합니다(FP32). 사용할 수 없으면 설정 오류를 알립니다. 실제 MPS 하드웨어 검증은 아직 하지 않았습니다.
- `LLM_LOAD_IN_4BIT=true`: CUDA에서만 사용하며 루트에서 `uv sync --locked --extra cuda`로 선택 의존성을 설치합니다. 기본값은 `false`입니다.
- `LLM_ADAPTER_ROOT`: 비워두면 `ai/app/adapters`. 외부 볼륨을 사용하면 절대 경로를 지정하세요. 아래에 `bank`, `insurance`, `securities` 폴더와 각각의 `adapter_config.json`, `adapter_model.safetensors`가 있어야 합니다.

기본 모델은 기존 어댑터와 일치하는 EXAONE 3.5 2.4B입니다. 최초 로드 시 Hugging Face에서 다운로드합니다.
오프라인 배포는 모델과 토크나이저, remote code를 미리 캐시에 준비하고 `HF_HUB_OFFLINE=1`을 설정하세요.
모델/어댑터 파일은 Git에 포함되지 않으므로 배포 시 별도로 제공해야 합니다.

```python
from app.llm.model import answer

print(answer("은행", "대출 만기를 연장하고 싶어요.", max_new_tokens=128))
```

자동 분류는 연결하지 않습니다. `model.answer`에 사용자가 고른 분야와 질문을 전달합니다.
반환값은 답변 문자열입니다.
수동 테스트는 루트에서 `uv run --locked jupyter lab ai/app/test.ipynb`를 실행한 뒤
노트북에 분야와 질문을 입력하세요. `종료`를 입력하면 끝납니다.

장치와 양자화 설정은 첫 로드에 적용됩니다. 변경 후 프로세스를 재시작하세요.
모델은 프로세스마다 한 벌씩 로드하므로 시작은 워커 1개로 하세요.
메모리 부족이나 로딩 오류는 숨기거나 다른 장치로 재시도하지 않고 호출자에게 전달합니다.

`/chat` 은 `app/services/chat_service.py` 에서 공용 DB 검색(RAG) → 분야 판단 → LLM 답변 → 이관 판단으로 연결되어 있습니다.
LLM 호출은 `.env` 의 `LLM_BACKEND` 로 고릅니다: `ollama`(기본, 로컬 개발용 base 모델) 또는 `transformers`
(이 문서의 `model.answer`, GPU 서버에서 분야별 어댑터 사용). 위 예제는 모델을 직접 호출하는 방법입니다.
실제 채팅 API 는 `AI_MOCK_MODE=false` 로 실행합니다.

검증: `cd ai` 후 `uv run --locked python -m pytest tests -q`.
장치별 로딩 설정은 모의 테스트로, CPU 생성은 소형 로컬 모델과 실제 PyTorch/PEFT로 확인합니다.
전체 EXAONE 가중치의 성능과 CUDA/MPS 하드웨어는 배포 환경에서 별도 확인해야 합니다.
