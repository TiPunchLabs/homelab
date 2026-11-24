"""Daily-cap rule and next-run computation for 5-field cron expressions (pure, no Hermes import).

A schedule is accepted only when Hermes parses it to a cron expression whose minute and hour are
one fixed number each: such an expression fires at most once per calendar day, whatever the day
fields say. Next runs are computed here, in the profile's timezone, with standard cron day
semantics (day-of-month OR day-of-week when both are restricted, as croniter does); the image
tests compare them with the ``next_run_at`` Hermes itself stores.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
_DAYS = {d: i for i, d in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"))}
_FIXED = re.compile(r"^\d{1,2}$")
_DAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


class ScheduleError(ValueError):
    """The expression is not a once-a-day-at-most cron expression."""


def _expand(field: str, low: int, high: int, names: dict[str, int] | None = None) -> set[int]:
    """Expand one cron field (``*``, lists, ranges, steps, names) into its values."""
    values: set[int] = set()
    for part in field.split(","):
        if not part:
            raise ScheduleError(f"champ vide dans « {field} »")
        step, has_step = 1, "/" in part
        if has_step:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise ScheduleError(f"pas invalide dans « {field} »")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        else:
            nums = []
            for b in part.split("-", 1):
                key = b.upper()
                if names and key in names:
                    nums.append(names[key])
                elif b.isdigit():
                    nums.append(int(b))
                else:
                    raise ScheduleError(f"valeur invalide « {b} »")
            start = nums[0]
            end = nums[1] if len(nums) == 2 else (high if has_step else nums[0])
        if start < low or end > high or start > end:
            raise ScheduleError(f"valeur hors limites dans « {field} »")
        values.update(range(start, end + 1, step))
    # Day-of-week 7 is Sunday, like 0.
    return {0 if (names is _DAYS and v == 7) else v for v in values}


def daily_fields(expr: str) -> tuple[int, int, str, str, str]:
    """Return (minute, hour, dom, month, dow) of a once-a-day-at-most expression, else raise."""
    parts = expr.split()
    if len(parts) != 5:
        raise ScheduleError("seule une expression cron à 5 champs est acceptée")
    minute, hour, dom, month, dow = parts
    if not (_FIXED.match(minute) and _FIXED.match(hour)):
        raise ScheduleError("la minute et l'heure doivent être un nombre fixe (au plus un passage par jour)")
    m, h = int(minute), int(hour)
    if not (0 <= m <= 59 and 0 <= h <= 23):
        raise ScheduleError("minute ou heure hors limites")
    # Validate the day fields now so a bad value is refused before anything is shown.
    _expand(dom, 1, 31)
    _expand(month, 1, 12, _MONTHS)
    _expand(dow, 0, 7, _DAYS)
    return m, h, dom, month, dow


def next_runs(expr: str, tz: ZoneInfo, now: datetime, count: int = 3) -> list[datetime]:
    """Next ``count`` fire instants (aware, in ``tz``) strictly after ``now``."""
    m, h, dom, month, dow = daily_fields(expr)
    doms, months = _expand(dom, 1, 31), _expand(month, 1, 12, _MONTHS)
    dows = _expand(dow, 0, 7, _DAYS)
    dom_any, dow_any = dom.startswith("*"), dow.startswith("*")
    local_now = now.astimezone(tz)
    day: date = local_now.date()
    found: list[datetime] = []
    for _ in range(366 * 8):
        cron_dow = (day.weekday() + 1) % 7
        if dom_any or dow_any:
            day_ok = (day.day in doms) and (cron_dow in dows)
        else:
            day_ok = (day.day in doms) or (cron_dow in dows)
        if day.month in months and day_ok:
            candidate = datetime.combine(day, time(h, m), tzinfo=tz)
            if candidate > local_now:
                found.append(candidate)
                if len(found) == count:
                    return found
        day += timedelta(days=1)
    return found


def format_fr(instant: datetime) -> str:
    """« lundi 24/11/2026 07:00 » in the instant's own timezone."""
    return f"{_DAYS_FR[instant.weekday()]} {instant:%d/%m/%Y %H:%M}"
