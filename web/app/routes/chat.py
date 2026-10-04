"""고객 채팅 화면 + 질문을 AI 서버로 전달 + 대화/상담 DB 저장.

고객 플로우
  채팅(/api/chat) ─┬─ 상담 종료(/api/end) ─▶ 만족도(/api/feedback, 1회) ─┬─ 만족/건너뜀 ─▶ 마무리
                   │                                                    └─ 불만족 ─▶ "상담사 연결이 필요하신가요?" ─ 아니요 ─▶ 마무리
                   │                                                                                             └ 네 ─▶ 아래로
                   └─ 상담사 연결(이름 입력, /api/handoff) ─▶ 만족도(1회) ─▶ 마무리
  마무리 ─▶ 세션 정리(/api/session/close) ─▶ 첫 화면(/)

고객은 로그인이 없다. 어떤 상담을 다루는지는 클라이언트가 보낸 id가 아니라 **세션 쿠키에 저장된 consult_id**만 믿는다.
"""
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, session

from app.extensions import db
from app.models import Consult, ConsultStatus, Customer, HandoffReason, Message, QueueType, Satisfaction, Sender
from app.services import ai_client
from app.services.business_hours import is_business_hours

bp = Blueprint("chat", __name__)

HISTORY_LIMIT = 6  # AI 서버에 같이 보내는 이전 대화 개수
_HISTORY_ROLE = {Sender.customer: "user", Sender.ai: "assistant"}
# AI 서버가 알려주는 이관 사유 코드 -> DB 이관 사유
_HANDOFF_REASONS = {
    "contact_request": HandoffReason.customer_request,
    "action_request": HandoffReason.action_request,
    "no_basis": HandoffReason.no_basis,
    "low_confidence": HandoffReason.low_confidence,
    "ai_error": HandoffReason.ai_error,
}


@bp.route("/chat")
def index():
    session.setdefault("session_id", str(uuid.uuid4()))  # AI 서버 호출용 (우리 DB의 customer_id와는 별개)
    return render_template("chat.html", business_hours=is_business_hours())


# --- 세션 <-> DB ---
def _get_or_create_customer() -> Customer:
    customer_id = session.get("customer_id")
    if customer_id:
        customer = db.session.get(Customer, customer_id)
        if customer:
            return customer
    customer = Customer()
    db.session.add(customer)
    db.session.flush()  # commit 전에 customer.customer_id 를 미리 받아오기 위함
    session["customer_id"] = customer.customer_id
    return customer


def _current_consult() -> Consult | None:
    """세션에 연결된 상담. 없으면 None."""
    consult_id = session.get("consult_id")
    return db.session.get(Consult, consult_id) if consult_id else None


def _get_or_create_open_consult() -> tuple[Consult, bool]:
    """AI와 상담 중(chatting)인 상담을 이어서 쓰고, 없거나 이미 끝났으면 새로 만든다. (상담, 새로 만들었는지)"""
    consult = _current_consult()
    if consult and consult.status == ConsultStatus.chatting:
        return consult, False
    consult = Consult(customer_id=_get_or_create_customer().customer_id, status=ConsultStatus.chatting)
    db.session.add(consult)
    db.session.flush()
    session["consult_id"] = consult.consult_id
    return consult, True


def _recent_history(consult: Consult) -> list[dict]:
    """이번 상담(consult)의 최근 고객/AI 발화를 오래된 순으로 돌려준다. 새 상담이면 빈 목록."""
    rows = db.session.scalars(
        db.select(Message)
        .where(Message.consult_id == consult.consult_id, Message.sender.in_(list(_HISTORY_ROLE)))
        .order_by(Message.message_id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [{"role": _HISTORY_ROLE[m.sender], "content": m.content} for m in reversed(rows)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _no_consult():
    return jsonify({"error": "no active consult"}), 400


# --- API ---
@bp.route("/api/chat", methods=["POST"])
def chat():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is empty"}), 400
    session.setdefault("session_id", str(uuid.uuid4()))

    consult, is_new = _get_or_create_open_consult()
    history = [] if is_new else _recent_history(consult)  # 새 상담이면 이전 대화가 없으니 조회를 건너뛴다(DB 왕복 절감). 현재 질문을 저장하기 전에 읽는다
    db.session.add(Message(consult_id=consult.consult_id, sender=Sender.customer, content=message))

    result = ai_client.ask(session["session_id"], message, history)

    db.session.add(Message(
        consult_id=consult.consult_id, sender=Sender.ai, content=result.get("answer", ""),
        sources=result.get("sources") or None,
    ))

    # 인사/감사 같은 응답은 분야가 없다(None). 이미 판단된 분야를 지우지 않도록 값이 있을 때만 갱신한다.
    if result.get("category") is not None:
        consult.category = result["category"]
        consult.topic = result.get("topic")
        consult.confidence = result.get("confidence")
    if result.get("handoff_needed"):
        # AI가 "상담사 연결이 필요하다"고 판단한 사유. 실제 접수(큐 등록)는 고객이 이름을 입력해야(/api/handoff) 확정된다.
        consult.handoff_reason = _HANDOFF_REASONS.get(result.get("handoff_code"), consult.handoff_reason)
        consult.handoff_detail = result.get("handoff_reason")

    db.session.commit()
    # 분류/근거/이관 사유 같은 내부·상담사용 정보는 위에서 DB에만 저장하고, 고객 브라우저에는 화면에 필요한 값만 내려보낸다.
    return jsonify({"answer": result.get("answer", ""), "handoff_needed": bool(result.get("handoff_needed"))})


@bp.route("/api/end", methods=["POST"])
def end():
    """고객이 '상담 종료'를 눌렀을 때. 상담사 연결 없이 AI 상담만으로 끝난 상담이 된다."""
    consult = _current_consult()
    if consult is None:
        return _no_consult()
    if consult.status == ConsultStatus.chatting:
        consult.status = ConsultStatus.ended
        consult.closed_at = _now()
        db.session.commit()
    return jsonify({"status": consult.status.value})


@bp.route("/api/feedback", methods=["POST"])
def feedback():
    """만족도 모달. 상담 하나에 한 번만 기록한다. satisfied: true / false / null(건너뛰기)."""
    consult = _current_consult()
    if consult is None:
        return _no_consult()

    satisfied = (request.get_json(silent=True) or {}).get("satisfied")
    if satisfied is not None and consult.satisfaction is None:
        consult.satisfaction = Satisfaction.satisfied if satisfied else Satisfaction.dissatisfied
        db.session.commit()

    # 상담을 종료(ended)하며 불만족이라고 답한 경우에만 "상담사 연결이 필요하신가요?"를 묻는다
    offer_handoff = consult.satisfaction == Satisfaction.dissatisfied and consult.status == ConsultStatus.ended
    return jsonify({"offer_handoff": offer_handoff})


@bp.route("/api/handoff", methods=["POST"])
def handoff():
    """상담사 연결: 이름을 받아 영업시간에 따라 실시간/익일 대기큐에 등록한다."""
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()[:50]
    if not name:
        return jsonify({"error": "name is required"}), 400

    consult = _current_consult()
    if consult is None:  # 아무 말도 안 하고 바로 '상담사 연결'을 누른 경우
        consult, _ = _get_or_create_open_consult()
    if consult.status in (ConsultStatus.waiting_realtime, ConsultStatus.waiting_next_day, ConsultStatus.completed):
        return jsonify({"error": "already handed off"}), 409

    ended_dissatisfied = consult.status == ConsultStatus.ended and consult.satisfaction == Satisfaction.dissatisfied
    business_hours = is_business_hours()
    consult.customer.name = name
    consult.status = ConsultStatus.waiting_realtime if business_hours else ConsultStatus.waiting_next_day
    consult.queue_type = QueueType.realtime if business_hours else QueueType.next_day  # 통계용, 이후 status가 바뀌어도 유지됨
    consult.handoff_at = _now()
    consult.closed_at = None
    consult.ai_category = consult.category  # 이 시점의 AI 분류를 고정해 둔다 (상담사가 재배정해도 오류율 계산 가능)
    if ended_dissatisfied:
        consult.handoff_reason = HandoffReason.user_dissatisfied
    elif consult.handoff_reason is None:
        consult.handoff_reason = HandoffReason.customer_request

    db.session.commit()
    return jsonify({"status": consult.status.value, "business_hours": business_hours})


@bp.route("/api/session/close", methods=["POST"])
def close_session():
    """마무리 후 고객 세션 정리. 다음에 들어오면 새 고객/새 상담으로 시작한다. (상담사 로그인 세션은 건드리지 않는다)"""
    for key in ("consult_id", "customer_id", "session_id"):
        session.pop(key, None)
    return jsonify({"ok": True})
