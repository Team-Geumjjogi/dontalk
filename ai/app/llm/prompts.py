"""★ 학습(ml/)과 서빙(ai/)이 똑같이 써야 하는 프롬프트 형식.

이 파일이 다르면 파인튜닝 효과가 사라집니다. 수정 시 팀 전체에 공지하세요.
"""
from typing import Optional

INSTRUCTION = (
    "당신은 금융 상담사입니다. 제공된 정보를 근거로 고객 문의에 정확하고 친절하게 답변하세요. "
    "제공된 RAG 데이터를 참고하되, 당신은 직접 행동을 할 수 없음을 인지하고 안내에 집중하세요"
    "마스킹 된 데이터. 개인 계좌·계약 정보등 개인정보를 직접 요구하지 말고, 준비나 과정에 대해서만 안내하시오"
)


def build_prompt(input_text: str, context: Optional[str] = None, instruction: str = INSTRUCTION) -> str:
    """모델에 넣을 최종 텍스트를 만든다."""
    parts = [f"### 지시\n{instruction}"]
    if context:
        parts.append(f"### 참고 정보\n{context}")
    parts.append(f"### 고객 문의\n{input_text}")
    parts.append("### 답변\n")
    return "\n\n".join(parts)
