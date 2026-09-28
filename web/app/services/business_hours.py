"""영업시간 판단. 플로우차트의 "영업시간 내/외" 분기에 쓴다.

평일(월~금) 09:00~18:00 을 영업시간으로 본다 (은행 영업시간 기준, 필요하면 팀 협의 후 조정).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18


def is_business_hours(now: datetime | None = None) -> bool:
    now = (now or datetime.now(KST)).astimezone(KST)
    is_weekday = now.weekday() < 5  # 0=월요일 ... 4=금요일, 5,6=주말
    return is_weekday and BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR
