"""Flask 확장 인스턴스.

`db`를 여기 따로 두는 이유: models/*.py 와 app/__init__.py 양쪽에서 가져다 써야 하는데,
app/__init__.py 안에 직접 두면 순환 import(app -> models -> app)가 생긴다.
"""
from datetime import datetime, timezone

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()


def utcnow() -> datetime:
    """모델의 시각 컬럼 default/onupdate 에 쓰는 헬퍼.

    datetime.utcnow() 는 Python 3.12부터 deprecated (naive datetime이라 timezone 정보가 없어서
    실수로 로컬시간처럼 다뤄지는 버그가 잦았음). 대신 timezone-aware 한 datetime.now(timezone.utc) 를 쓴다.
    """
    return datetime.now(timezone.utc)
