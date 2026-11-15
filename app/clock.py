import os  # read settings from the environment (.env)
from datetime import date, datetime, time, timedelta, timezone  # dates, times and time zones

LOCAL_TZ = timezone(timedelta(hours=float(os.getenv("UTC_OFFSET_HOURS", "5"))))  # the users' clock: Pakistan = UTC+5 all year (no daylight saving)


def utc_now() -> datetime:  # the time right now in UTC (tests replace this to "freeze" time)
    return datetime.now(timezone.utc)


def local_now() -> datetime:  # the time right now on the users' clock
    return utc_now().astimezone(LOCAL_TZ)  # e.g. 2026-11-15 00:40 +05:00


def to_utc(day: date, at: time) -> datetime:  # a day + clock time in Pakistan -> the same moment in UTC
    return datetime.combine(day, at, tzinfo=LOCAL_TZ).astimezone(timezone.utc)  # 2026-11-16 20:00 PKT -> 15:00 UTC


def local_today() -> date:  # today's date on the users' clock (NOT the server's, which may be UTC)
    return local_now().date()  # e.g. 2026-11-15
