"""역할(role) 기반 접근 제어.

Spring Security의 `@PreAuthorize("hasRole('ADMIN')")`에 해당하는 것을 직접 만든다.
Flask-Login은 "로그인했는지"(`@login_required`)까지만 봐주고, "어떤 역할인지"는 안 봐주기 때문.
"""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.models import EmployeeRole


def role_required(*roles: EmployeeRole):
    """지정한 role 중 하나가 아니면 403(권한 없음)을 돌려준다.

    사용 예:
        @bp.route("/admin/")
        @role_required(EmployeeRole.admin)
        def dashboard(): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required  # 먼저 로그인 여부부터 확인 (비로그인이면 로그인 페이지로 리다이렉트)
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
