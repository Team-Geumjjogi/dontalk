"""첫 화면(랜딩). 고객은 여기서 상담을 시작하고, 상담사/관리자는 오른쪽 위 버튼으로 로그인 화면에 간다."""
from flask import Blueprint, render_template

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    return render_template("landing.html")
