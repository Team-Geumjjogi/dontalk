"""상담사/관리자 로그인. (고객은 로그인이 없다 — chat.py 에서 세션 쿠키만 씀)"""
from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

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
        return render_template("login.html", error="이메일 또는 비밀번호가 올바르지 않습니다.", email=email), 401

    login_user(employee)  # 세션에 "이 사람이 로그인했다"를 기록 (Spring의 SecurityContext에 Authentication 채우는 것과 같은 역할)

    if employee.role == EmployeeRole.admin:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("agent.queue"))


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
