"""AI 분류 정확도 집계 (관리자 대시보드).

- 대상: 상담사 연결이 접수된(handoff_at) 상담 중, AI가 분야를 판단한(ai_category) 건
- 오분류: 상담사가 AI가 판단한 분야에서 다른 분야로 재배정한(consult_transfer.from_category == ai_category) 건
- AI가 분야를 판단하지 못한 건(ai_category 없음)은 오분류가 아니라 "AI 미분류"로 따로 센다
"""
from sqlalchemy import distinct, func

from app.extensions import db
from app.models import CATEGORIES, Consult, ConsultTransfer


def classification_stats() -> dict:
    """{"rows": [{category, handed_off, reassigned, error_rate}...], "total": {...}, "unclassified": n}"""
    handed_off = dict(db.session.execute(
        db.select(Consult.ai_category, func.count(Consult.consult_id))
        .where(Consult.handoff_at.isnot(None), Consult.ai_category.in_(CATEGORIES))
        .group_by(Consult.ai_category)
    ).all())
    reassigned = dict(db.session.execute(
        db.select(Consult.ai_category, func.count(distinct(Consult.consult_id)))
        .join(ConsultTransfer, ConsultTransfer.consult_id == Consult.consult_id)
        .where(ConsultTransfer.from_category == Consult.ai_category, Consult.ai_category.in_(CATEGORIES))
        .group_by(Consult.ai_category)
    ).all())
    unclassified = db.session.scalar(
        db.select(func.count(Consult.consult_id)).where(Consult.handoff_at.isnot(None), Consult.ai_category.is_(None))
    )

    def row(category: str, handed: int, wrong: int) -> dict:
        return {"category": category, "handed_off": handed, "reassigned": wrong,
                "error_rate": round(wrong / handed * 100, 1) if handed else None}

    rows = [row(c, handed_off.get(c, 0), reassigned.get(c, 0)) for c in CATEGORIES]
    return {
        "rows": rows,
        "total": row("전체", sum(r["handed_off"] for r in rows), sum(r["reassigned"] for r in rows)),
        "unclassified": unclassified or 0,
    }
