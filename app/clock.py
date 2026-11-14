import os  # read settings from the environment (.env)
from datetime import date, datetime, timedelta, timezone  # dates, times and time zones

LOCAL_TZ = timezone(timedelta(hours=float(os.getenv("UTC_OFFSET_HOURS", "5"))))  # the users' clock: Pakistan = UTC+5 all year (no daylight saving)


def local_now() -> datetime:  # the time right now on the users' clock
    return datetime.now(LOCAL_TZ)  # e.g. 2026-11-15 00:40 +05:00


def local_today() -> date:  # today's date on the users' clock (NOT the server's, which may be UTC)
    return local_now().date()  # e.g. 2026-11-15
