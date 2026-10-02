"""EXAONE 2.4B와 분야별 LoRA 로드 및 답변 생성.

최초 호출 시 모델을 로드한다. 기본값은 CUDA 자동 선택, 없으면 CPU 실행이다.
LLM_DEVICE=cpu/cuda/mps로 장치를 지정할 수 있다. 4bit는 CUDA에서 선택 사용한다.
어댑터 위치: ai/app/adapters/{bank,insurance,securities}/
"""
from importlib.util import find_spec
from pathlib import Path
from threading import RLock

from ..core import config
from .prompts import INSTRUCTION

MODEL_ID = "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
ADAPTER_ROOT = Path(__file__).resolve().parent.parent / "adapters"
ADAPTER_NAMES = {"은행": "bank", "보험": "insurance", "증권": "securities"}

_runtime = None
# ponytail: 한 프로세스에서 생성은 직렬 처리. 처리량이 부족하면 GPU별 워커로 분리한다.
_lock = RLock()


def load_model():
    """세 어댑터를 탑재한 (model, tokenizer)를 프로세스당 한 번 로드한다."""
    global _runtime
    with _lock:
        if _runtime is not None:
            return _runtime

        adapter_root = Path(config.LLM_ADAPTER_ROOT).expanduser() if config.LLM_ADAPTER_ROOT else ADAPTER_ROOT
        for category, name in ADAPTER_NAMES.items():
            for filename in ("adapter_config.json", "adapter_model.safetensors"):
                path = adapter_root / name / filename
                if not path.is_file():
                    raise FileNotFoundError(f"{category} 어댑터 파일이 없습니다: {path}")

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        device = config.LLM_DEVICE
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device not in {"cpu", "cuda", "mps"}:
            raise ValueError("LLM_DEVICE는 auto, cpu, cuda, mps 중 하나여야 합니다.")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA를 사용할 수 없습니다. LLM_DEVICE=cpu 또는 auto로 설정하세요.")
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS를 사용할 수 없습니다. LLM_DEVICE=cpu 또는 auto로 설정하세요.")

        load_options = {
            "device_map": {"": device},
            "dtype": torch.float16 if device == "cuda" else torch.float32,
        }
        if config.LLM_LOAD_IN_4BIT not in {"true", "false"}:
            raise ValueError("LLM_LOAD_IN_4BIT는 true 또는 false여야 합니다.")
        if config.LLM_LOAD_IN_4BIT == "true":
            if device != "cuda":
                raise ValueError("4bit 모드는 CUDA 전용입니다. LLM_LOAD_IN_4BIT=false로 설정하세요.")
            if find_spec("bitsandbytes") is None:
                raise RuntimeError("4bit 모드에는 bitsandbytes 설치가 필요합니다.")
            load_options["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )

        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token

        base_model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            **load_options,
        )
        # EXAONE의 입력 임베딩을 PEFT가 찾을 수 있도록 지정한다.
        base_model.transformer._input_embed_layer = "wte"
        base_model.config.use_cache = True
        model = PeftModel.from_pretrained(
            base_model, str(adapter_root / "bank"),
            adapter_name="bank", is_trainable=False,
        )
        for name in ("insurance", "securities"):
            model.load_adapter(
                str(adapter_root / name), adapter_name=name, is_trainable=False,
            )
        model.eval()
        _runtime = (model, tokenizer)
        return _runtime


def answer(category: str, question: str, max_new_tokens: int = 512) -> str:
    """은행/보험/증권 어댑터를 선택하고 프롬프트를 제외한 답변을 반환한다."""
    if category not in ADAPTER_NAMES:
        raise ValueError(f"지원하지 않는 분야입니다: {category}. 사용 가능: {list(ADAPTER_NAMES)}")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("질문은 비어 있지 않은 문자열이어야 합니다.")
    if type(max_new_tokens) is not int or max_new_tokens <= 0:
        raise ValueError("max_new_tokens는 양의 정수여야 합니다.")

    with _lock:
        model, tokenizer = load_model()
        import torch

        model.set_adapter(ADAPTER_NAMES[category])
        model.eval()
        inputs = tokenizer.apply_chat_template(
            [
                {"role": "system", "content": INSTRUCTION},
                {"role": "user", "content": question},
            ],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        device = model.get_input_embeddings().weight.device
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                repetition_penalty=1.05,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
        generated_ids = outputs[0, inputs["input_ids"].shape[-1]:]
        return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
