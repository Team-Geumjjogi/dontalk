# 여러가지 질문을 통해 성능 점검

완전히 튜닝된 것이 아니라 그에서 오는 문제점 ( 모든 세부 실행 방안을 알지는 못함 )은 있음 .
질문은 validation set에 포함되어있던 내용.

```python
import json
import random
from contextlib import nullcontext
from pathlib import Path
import numpy as np
import torch
from google.colab import drive
from peft import PeftModel
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

if not torch.cuda.is_available():
    raise RuntimeError('Colab 런타임을 GPU(T4)로 변경하세요.')
drive.mount('/content/drive')
drive_dir = Path('/content/drive/MyDrive/dontalk')
rag_path = drive_dir / 'rag_dataset.jsonl'
embedding_path = drive_dir / 'rag_embeddings.npy'
adapter_dir = drive_dir / 'exaone35-2.4b-qlora-v2'

for path in (rag_path, embedding_path, adapter_dir / 'adapter_config.json'):
    if not path.exists():
        raise FileNotFoundError(f'필요한 파일이 없습니다: {path}')

model_id = 'LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct'
embedding_model_id = 'dragonkue/snowflake-arctic-embed-l-v2.0-ko'
system_message = (
    '당신은 한국어 금융 상담원입니다. 질문에 직접 답하고, '
    '제공된 정보에 없는 수수료나 절차는 사실처럼 단정하지 마세요.'
)

max_new_tokens = 1000
tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
base_model = AutoModelForCausalLM.from_pretrained(
    model_id, trust_remote_code=True, device_map='auto', dtype=torch.float16,
    quantization_config=BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type='nf4',
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16,
    ),
)

base_model.transformer._input_embed_layer = 'wte'
assert base_model.get_input_embeddings() is base_model.transformer.wte
llm = PeftModel.from_pretrained(base_model, str(adapter_dir)).eval()
llm.config.use_cache = True

with rag_path.open(encoding='utf-8') as source:
    rag_texts = [json.loads(line)['text'] for line in source]
document_embeddings = np.load(embedding_path).astype('float32')
if len(rag_texts) != len(document_embeddings):
    raise ValueError('RAG 문서 수와 임베딩 수가 다릅니다.')
document_embeddings /= np.linalg.norm(document_embeddings, axis=1, keepdims=True)
embedding_model = SentenceTransformer(embedding_model_id, device='cpu')

def search_documents(query, top_k=5):
    query_embedding = embedding_model.encode(
        [query], prompt_name='query', convert_to_numpy=True, normalize_embeddings=True
    )[0]
    scores = document_embeddings @ query_embedding
    top_indices = np.argpartition(scores, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
    return [
        {'rank': rank, 'score': float(scores[i]), 'text': rag_texts[i]}
        for rank, i in enumerate(top_indices, start=1)
    ]

def generate_answer(user_content, tuned):
    inputs = tokenizer.apply_chat_template(
        [{'role': 'system', 'content': system_message},
         {'role': 'user', 'content': user_content}],
        tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors='pt'
    ).to(llm.device)
    adapter_context = nullcontext() if tuned else llm.disable_adapter()
    with adapter_context, torch.inference_mode():
        generated = llm.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(
        generated[0, inputs['input_ids'].shape[1]:], skip_special_tokens=True
    )
```


```python
import time

while True:
    question = input(
        "안녕하세요, 저는 금융 도우미 돈톡입니다! 무엇을 도와드릴까요?\n"
        "질문을 입력해주시고, 종료하려면 [종료]라고 입력해주세요!\n"
    )

    if question == "종료":
        break

    start = time.perf_counter()

    rag_documents = search_documents(question)
    rag_context = '\n'.join(doc['text'] for doc in rag_documents)
    retrieval_end = time.perf_counter()

    llm_input = f"{question}\n\n검색 문서:\n{rag_context}"
    answer = generate_answer(llm_input, tuned=True)
    end = time.perf_counter()

    print(answer)
    print(
        f"\n검색: {retrieval_end - start:.2f}초 | "
        f"답변 생성: {end - retrieval_end:.2f}초 | "
        f"전체 응답: {end - start:.2f}초"
    )
```



## 직접 행동을 문의하는 경우

### Q. 그 아이디 삭제 좀 부탁드릴게요. 더 이상 사용하실 계획이 없어서요.

```
계좌 폐쇄와 아이디 삭제를 동시에 진행하며, 전자금융 서비스 해지와 마케팅 동의를 미동의로 변경합니다. 현재 모바일 앱에 로그인 중이시면 로그아웃 후 재로그인해 주시고, 로그아웃을 하지 않으면 아이디 삭제가 제한됩니다. 정산이 완료되면 계좌 폐쇄가 시스템에 접수되고, 3영업일 이내에 최종 명세서를 이메일로 발송해 드립니다. 모든 절차가 완료되면 계좌와 아이디가 모두 삭제됩니다.
```
> 엉뚱한 대답 + 실제 작업하지 않았지만 학습 내용에 따라 작업을 전제로 진행했음

## 연계되는 활동 질문


### Q. 원데이 보험에 가입해둔 상태인데 이번에 취소를 하려고 합니다. 가능한 한 빨리 취소 절차를 진행해 주셨으면 해서 연락드렸습니다. 어떻게 하면 빠르게 처리할 수 있을까요?

```
원데이 보험 가입 절차를 안내해 드리겠습니다. 먼저 고객님의 성함과 생년월일을 확인하고, 차량 번호와 등록된 주소를 입력해 주셔야 합니다. 입력하신 정보를 바탕으로 시스템에서 보장 범위와 보험료를 조회한 후, 고객님께서 선택하신 보장 옵션에 따라 최종 금액을 산출합니다. 산출된 금액은 카드 결제로 진행되며, 결제가 완료되면 보험 계약이 자동으로 체결됩니다. 결제가 승인되지 않은 경우에는 즉시 취소가 가능하며, 취소 시 환불 절차가 진행됩니다. 취소를 원하시면 고객센터로 연락 주시면 전액 환불해 드립니다.
```
> 잘못된 안내

### Q. 지금 제 계좌에 남아 있는 포인트가 있는데, 혹시 제가 카드가 없는 상황에서도 이 포인트를 사용할 수 있는 방법이 있을까요?

```
잔고가 없으시면 연동된 포인트와 쿠폰은 자동으로 소멸되며, 펀드와 같은 연계 서비스가 있을 경우 별도의 해지 절차가 필요합니다. 계좌 해지는 영구적이지만, 추후 새 계좌를 개설하실 경우 기존 정보와는 별도로 신규 가입 절차를 진행하시면 됩니다.
```

> 할루시네이션

### Q. 일일 이체 한도를 올리려고 여러 번 시도했는데 계속 실패하고, 시스템에서는 대상 계좌가 아니라는 안내만 반복해서 나와서 정확히 어떤 문제인지, 그리고 어떻게 해야 한도를 정상적으로 상향할 수 있는지 자세히 알고 싶습니다.

```
고객님께서는 현재 일일 이체 한도가 ●●원으로 제한되어 있으며, 이 한도는 보안 정책에 따라 자동 적용됩니다. 한도 상향을 원하시면 가까운 영업점을 방문하셔서 신분증과 거래 목적을 증명할 수 있는 서류를 지참하시고 상담을 받으셔야 합니다. 방문 시 영업점 직원이 한도 상향 신청을 도와드리며, 필요한 서류는 급여명세서나 거래 내역서 등 객관적인 증빙 자료입니다.
```

> 마스킹 된 정보의 제공 -> 그대로 응답에 출력

## 없는 걸 묻는 경우

### Q. 피보나치 되돌림 도구를 사용하고 싶은데, 저희 HTS에서 해당 기능을 어디에서 찾을 수 있는지 알려주실 수 있나요?

```
피봇과 골든크로스를 설정하려면 먼저 차트 화면 하단의 ‘시험증권’ 메뉴를 열고, 지표 메뉴에서 ‘피봇’과 ‘골든크로스’ 관련 지표를 선택하십시오. 골든크로스는 기본 제공되지 않으므로 직접 수식을 작성하거나 커스텀 지표를 생성해야 합니다. 커스텀 지표를 이용할 경우, 하나당 월 5,000원의 이용료가 부과되며, 현재 진행 중인 프로모션 적용 시 월 2,500원에 이용하실 수 있습니다. 설정을 저장하고 싶으시면 템플릿 이름을 알려주시면 바로 저장해 드리겠습니다.
```

> 실제로는 피보나치 되돌림 도구는 없음. 할루시네이션을 최소화 해야 함.

## 일반 문의

### Q. 암보험에 대해서도 궁금한 점이 있어서 자세히 문의드리고 싶은데, 혹시 암보험 상품이 어떤 보장 내용을 포함하고 있는지 구체적으로 안내받을 수 있을까요?

```
암보험은 암 진단 시 지급되는 진단금과 입원일당, 수술비를 포함한 다양한 보장을 제공합니다. 보장금액은 계약 시 설정된 금액이며, 보험료는 카드로 자동 납부됩니다. 자세한 보장 내용과 금액은 계약서에 명시되어 있으니, 필요 시 계약서를 확인하실 수 있습니다.
```

> 있으나 마나한 대답 출력, 그래서 보장 목록에 뭐가 있는데 링크를 주던가..


## 튜닝이 완전하게 진행 + 마스킹 데이터 처리 로직 필요 + 실제 안내 수준으로 다듬어야 할 필요 있음 => 큰 모델로 올라가거나, 실제 업무 크롤링을 넣으면 잘 될지도?