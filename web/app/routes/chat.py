"""고객 채팅 화면 + 질문을 AI 서버로 전달 + 대화/상담 DB 저장.

흐름: 고객이 메시지를 보내면 -> (필요시 Customer/Consult 새로 생성) -> 메시지 저장
      -> AI 서버 호출 -> AI 응답 메시지 저장 -> 응답 반환
만족/불만족 버튼을 누르면 -> 그 상담(consult)에 결과를 기록하고 종료(또는 상담사 이관 표시).

TODO(웹 담당, 4단계): "상담사 연결하기" 버튼 클릭 시 이름 입력 폼 -> 대기큐 등록.
"""
import uuid

from flask import Blueprint, jsonify, render_template, request, session

from app.extensions import db
from app.models import Consult, ConsultStatus, Customer, HandoffReason, Message, Satisfaction, Sender
from app.services import ai_client

bp = Blueprint("chat", __name__)


@bp.route("/")
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
    """만족/불만족으로 이미 끝난 상담이면 새로 만들고, 진행 중이면 이어서 쓴다."""
    consult_id = session.get("consult_id")
    if consult_id:
        consult = db.session.get(Consult, consult_id)
        if consult and consult.status not in (ConsultStatus.completed,):
            return consult
    consult = Consult(customer_id=customer.customer_id, status=ConsultStatus.ai_resolved)
    db.session.add(consult)
    db.session.flush()
    session["consult_id"] = consult.consult_id
    return consult


@bp.route("/api/chat", methods=["POST"])
def chat():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is empty"}), 400
    session.setdefault("session_id", str(uuid.uuid4()))

    customer = _get_or_create_customer()
    consult = _get_or_create_open_consult(customer)

    db.session.add(Message(consult_id=consult.consult_id, sender=Sender.customer, content=message))

    result = ai_client.ask(session["session_id"], message)

    db.session.add(Message(consult_id=consult.consult_id, sender=Sender.ai, content=result.get("answer", "")))

    consult.category = result.get("category")
    consult.topic = result.get("topic")
    consult.confidence = result.get("confidence")
    if result.get("handoff_needed"):
        consult.status = ConsultStatus.waiting_realtime  # 영업시간 판단은 4단계에서 다듬는다
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
        if consult.status != ConsultStatus.waiting_realtime:
            consult.status = ConsultStatus.waiting_realtime

    db.session.commit()
    return jsonify({
        "status": consult.status.value,
        "handoff_needed": consult.status != ConsultStatus.completed,
    })
