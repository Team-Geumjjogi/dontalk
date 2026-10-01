"""AI 분류 정확도 집계 (관리자 대시보드).

- 대상: 상담사 연결이 접수된(handoff_at) 상담 중, AI가 분야를 판단한(ai_category) 건
- 오분류: 상담사가 AI가 판단한 분야에서 다른 분야로 재배정한(consult_transfer.from_category == ai_category) 건
- AI가 분야를 판단하지 못한 건(ai_category 없음)은 오분류가 아니라 "AI 미분류"로 따로 센다
"""
from sqlalchemy import exists, func

from app.extensions import db
from app.models import CATEGORIES, Consult, ConsultTransfer


def classification_stats() -> dict:
    """{"rows": [{category, handed_off, reassigned, error_rate}...], "total": {...}, "unclassified": n}  (쿼리 한 번)"""
    reassigned_after_ai_pick = exists().where(
        ConsultTransfer.consult_id == Consult.consult_id, ConsultTransfer.from_category == Consult.ai_category
    )
    rows_by_ai_category = {
        category: (handed, wrong)
        for category, handed, wrong in db.session.execute(
            db.select(Consult.ai_category, func.count(Consult.consult_id), func.count().filter(reassigned_after_ai_pick))
            .where(Consult.handoff_at.isnot(None))
            .group_by(Consult.ai_category)
        ).all()
    }

    def row(category: str, handed: int, wrong: int) -> dict:
        return {"category": category, "handed_off": handed, "reassigned": wrong,
                "error_rate": round(wrong / handed * 100, 1) if handed else None}

    rows = [row(c, *rows_by_ai_category.get(c, (0, 0))) for c in CATEGORIES]
    return {
        "rows": rows,
        "total": row("전체", sum(r["handed_off"] for r in rows), sum(r["reassigned"] for r in rows)),
        "unclassified": rows_by_ai_category.get(None, (0, 0))[0],
    }
