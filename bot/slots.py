"""Расчёт свободного времени: график мастера − перерывы − занятые записи.

Все функции чистые (без базы и Telegram), всё время — «наивное» местное время
салона. Поэтому их легко проверять тестами.
"""
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta

from .salon import Master

Interval = tuple[datetime, datetime]  # [начало, конец)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Пересекаются ли промежутки. Стык (10:00–11:00 и 11:00–12:00) — не пересечение."""
    return a_start < b_end and b_start < a_end


def free_slots(master: Master, day: date, minutes: int, busy: Iterable[Interval],
               step: int, earliest: datetime) -> list[datetime]:
    """Время начала, на которое к мастеру можно записаться на услугу длиной minutes.

    busy     — уже занятые промежутки мастера (записи);
    step     — шаг сетки в минутах, сетка считается от начала рабочего дня;
    earliest — раньше этого момента записываться нельзя (сейчас + запас).
    """
    if not master.works_on(day.weekday()):
        return []
    work_start = datetime.combine(day, master.start)
    work_end = datetime.combine(day, master.end)
    length = timedelta(minutes=minutes)
    blocked = [(datetime.combine(day, s), datetime.combine(day, e)) for s, e in master.breaks]
    blocked += list(busy)

    result = []
    slot = work_start
    while slot + length <= work_end:
        end = slot + length
        if slot >= earliest and not any(overlaps(slot, end, b, e) for b, e in blocked):
            result.append(slot)
        slot += timedelta(minutes=step)
    return result


def free_slots_any(masters: Iterable[Master], day: date, minutes: int,
                   busy: Mapping[str, Iterable[Interval]], step: int,
                   earliest: datetime) -> dict[datetime, list[str]]:
    """Для «любого мастера»: время → кто из мастеров свободен в это время.

    busy — занятые промежутки по имени мастера. Время отсортировано.
    """
    result: dict[datetime, list[str]] = {}
    for master in masters:
        for slot in free_slots(master, day, minutes, busy.get(master.name, ()), step, earliest):
            result.setdefault(slot, []).append(master.name)
    return dict(sorted(result.items()))


def booking_days(today: date, days_ahead: int) -> list[date]:
    """Дни, на которые можно записаться: сегодня и ещё days_ahead − 1 дней."""
    return [today + timedelta(days=i) for i in range(days_ahead)]
