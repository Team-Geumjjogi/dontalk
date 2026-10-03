"""Top-K 검색 결과의 메타데이터를 집계해 금융 분야(은행/보험/증권)와 확신도를 판단한다."""
from collections import Counter
from typing import List, Optional, Tuple


def _most_common_by_rank(values: List[str]) -> Optional[str]:
    """최빈값. 동률이면 검색 순위가 높은(리스트에서 먼저 나온) 값."""
    if not values:
        return None
    counts = Counter(values)
    best = max(counts.values())
    return next(v for v in values if counts[v] == best)


def decide(docs: List[dict]) -> Tuple[Optional[str], Optional[str], float]:
    """(분야, 상세 주제, 확신도)를 돌려준다. 확신도 = 선택된 분야가 Top-K 에서 차지하는 비율(0~1).

    docs 는 retriever.search 결과(유사도 높은 순). 검색 결과가 없거나 분야 값이 없으면 (None, None, 0.0).
    """
    categories = [d["consulting_category"] for d in docs if d.get("consulting_category")]
    category = _most_common_by_rank(categories)
    if category is None:
        return None, None, 0.0
    topics = [d["consulting_topic"] for d in docs if d.get("consulting_category") == category and d.get("consulting_topic")]
    topic = _most_common_by_rank(topics)
    confidence = categories.count(category) / len(docs)
    return category, topic, confidence
