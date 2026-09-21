"""간이 로그인. (회원가입/비밀번호 없음. 고객/상담사 역할만 선택)

TODO(웹 담당): 로그인 화면(templates/login.html), 상담사 화면 분기.
"""
from flask import Blueprint, redirect, session, url_for

bp = Blueprint("auth", __name__)


@bp.route("/login/<role>")
def login(role):
    if role not in ("customer", "agent"):
        return "역할은 customer 또는 agent 입니다.", 400
    session["role"] = role
    return redirect(url_for("chat.index"))
