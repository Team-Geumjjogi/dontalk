"""상담사/관리자 로그인. (고객은 로그인이 없다 — chat.py 에서 세션 쿠키만 씀)"""
from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.authz import role_required
from app.models import Employee, EmployeeRole

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    employee = Employee.query.filter_by(email=email).first()
    if employee is None or not employee.check_password(password):
        return render_template("login.html", error="이메일 또는 비밀번호가 올바르지 않습니다."), 401

    login_user(employee)  # 세션에 "이 사람이 로그인했다"를 기록 (Spring의 SecurityContext에 Authentication 채우는 것과 같은 역할)

    if employee.role == EmployeeRole.admin:
        return redirect(url_for("auth.admin_home"))
    return redirect(url_for("auth.agent_home"))


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# --- 역할별 홈. 실제 화면(대기큐/대시보드)은 5, 6단계에서 채운다. 지금은 권한 체크만 확인하는 용도. ---

@bp.route("/agent/")
@role_required(EmployeeRole.agent)
def agent_home():
    return f"상담사 홈 (개발 중) — 안녕하세요, {current_user.name}님"


@bp.route("/admin/")
@role_required(EmployeeRole.admin)
def admin_home():
    return f"관리자 홈 (개발 중) — 안녕하세요, {current_user.name}님"
