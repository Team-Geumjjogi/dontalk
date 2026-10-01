"""고객 채팅 화면 + 질문을 AI 서버로 전달 + 대화/상담 DB 저장.

흐름: 고객이 메시지를 보내면 -> (필요시 Customer/Consult 새로 생성) -> 메시지 저장
      -> AI 서버 호출 -> AI 응답 메시지 저장 -> 응답 반환
만족/불만족 버튼을 누르면 -> 그 상담(consult)에 결과를 기록하고 종료(또는 상담사 이관 필요 표시).
"상담사 연결하기" -> 이름 입력 -> /api/handoff -> 영업시간에 따라 실시간/익일 대기큐 등록.
"""
import uuid

from flask import Blueprint, jsonify, render_template, request, session

from app.extensions import db
from app.models import Consult, ConsultStatus, Customer, HandoffReason, Message, QueueType, Satisfaction, Sender
from app.services import ai_client
from app.services.business_hours import is_business_hours

bp = Blueprint("chat", __name__)


@bp.route("/chat")
def index():
    session.setdefault("session_id", str(uuid.uuid4()))  # AI 서버 호출용 (우리 DB의 customer_id와는 별개)
    return render_template("chat.html")


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


def _get_or_create_open_consult(customer: Customer) -> Consult:
    """이미 끝났거나(completed) 대기큐에 들어간(waiting_*) 상담이 아니면 이어서 쓰고, 아니면 새로 만든다."""
    consult_id = session.get("consult_id")
    if consult_id:
        consult = db.session.get(Consult, consult_id)
        open_statuses = (ConsultStatus.ai_resolved,)
        if consult and consult.status in open_statuses:
            return consult
    consult = Consult(customer_id=customer.customer_id, status=ConsultStatus.ai_resolved)
    db.session.add(consult)
    db.session.flush()
    session["consult_id"] = consult.consult_id
    return consult


HISTORY_LIMIT = 6  # AI 서버에 같이 보내는 이전 대화 개수
_HISTORY_ROLE = {Sender.customer: "user", Sender.ai: "assistant"}  # 상담사(agent) 발화는 AI 대화가 아니라 제외


def _recent_history(consult: Consult) -> list[dict]:
    """이번 상담(consult)의 최근 고객/AI 발화를 오래된 순으로 돌려준다. 새 상담이면 빈 목록."""
    rows = db.session.scalars(
        db.select(Message)
        .where(Message.consult_id == consult.consult_id, Message.sender.in_(list(_HISTORY_ROLE)))
        .order_by(Message.message_id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [{"role": _HISTORY_ROLE[m.sender], "content": m.content} for m in reversed(rows)]


@bp.route("/api/chat", methods=["POST"])
def chat():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is empty"}), 400
    session.setdefault("session_id", str(uuid.uuid4()))

    customer = _get_or_create_customer()
    consult = _get_or_create_open_consult(customer)

    history = _recent_history(consult)  # 현재 질문을 저장하기 전에 읽어서 '이전 대화'만 담는다
    db.session.add(Message(consult_id=consult.consult_id, sender=Sender.customer, content=message))

    result = ai_client.ask(session["session_id"], message, history)

    db.session.add(Message(consult_id=consult.consult_id, sender=Sender.ai, content=result.get("answer", "")))

    # 인사/감사 같은 응답은 분야가 없다(None). 이미 판단된 분야를 지우지 않도록 값이 있을 때만 갱신한다.
    if result.get("category") is not None:
        consult.category = result["category"]
        consult.topic = result.get("topic")
        consult.confidence = result.get("confidence")
    if result.get("handoff_needed"):
        # 큐 상태(실시간/익일)는 아직 안 정한다 -- 이름을 받아야(/api/handoff) 확정된다.
        consult.handoff_reason = HandoffReason.ai_low_confidence

    db.session.commit()

    result["consult_id"] = consult.consult_id
    return jsonify(result)


@bp.route("/api/feedback", methods=["POST"])
def feedback():
    """만족/불만족 버튼 처리."""
    data = request.get_json(silent=True) or {}
    consult_id = data.get("consult_id")
    satisfied = data.get("satisfied")  # true / false

    consult = db.session.get(Consult, consult_id) if consult_id else None
    if consult is None:
        return jsonify({"error": "consult not found"}), 404

    if satisfied:
        consult.satisfaction = Satisfaction.satisfied
        consult.status = ConsultStatus.completed
    else:
        consult.satisfaction = Satisfaction.dissatisfied
        if consult.handoff_reason is None:
            consult.handoff_reason = HandoffReason.user_dissatisfied

    db.session.commit()
    return jsonify({
        "status": consult.status.value,
        "handoff_needed": consult.handoff_reason is not None and consult.status != ConsultStatus.completed,
    })


@bp.route("/api/handoff", methods=["POST"])
def handoff():
    """'상담사 연결하기' 이름 입력 제출 -> 영업시간에 따라 실시간/익일 대기큐 등록."""
    data = request.get_json(silent=True) or {}
    consult_id = data.get("consult_id")
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    consult = db.session.get(Consult, consult_id) if consult_id else None
    if consult is None:
        return jsonify({"error": "consult not found"}), 404

    consult.customer.name = name
    business_hours = is_business_hours()
    consult.status = ConsultStatus.waiting_realtime if business_hours else ConsultStatus.waiting_next_day
    consult.queue_type = QueueType.realtime if business_hours else QueueType.next_day  # 통계용, 이후 status가 바뀌어도 유지됨
    if consult.handoff_reason is None:
        consult.handoff_reason = HandoffReason.user_dissatisfied

    db.session.commit()

    return jsonify({
        "status": consult.status.value,
        "business_hours": consult.status == ConsultStatus.waiting_realtime,
    })
