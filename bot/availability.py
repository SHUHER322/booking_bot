"""Свободные дни и время с учётом базы: связывает salon.toml, записи и slots.py."""
from datetime import date, datetime

from .db import Database
from .salon import Master, Salon, Service
from .slots import booking_days, free_slots_any


def candidates(salon: Salon, service: Service, master: str | None) -> tuple[Master, ...]:
    """Кого рассматриваем: выбранного мастера или всех, кто делает услугу."""
    if master is None:
        return salon.masters_for(service.name)
    found = salon.master(master)
    return (found,) if found and found.does(service.name) else ()


async def free_days(db: Database, salon: Salon, service: Service,
                    master: str | None, now: datetime) -> list[date]:
    """Дни, в которые есть хотя бы одно свободное время."""
    masters = candidates(salon, service, master)
    days = booking_days(now.date(), salon.days_ahead)
    busy = await db.busy_between(days[0], days[-1])
    earliest = now + salon.min_before
    return [day for day in days
            if free_slots_any(masters, day, service.minutes, busy.get(day, {}),
                              salon.slot_step, earliest)]


async def free_times(db: Database, salon: Salon, service: Service, master: str | None,
                     day: date, now: datetime) -> dict[datetime, list[str]]:
    """Свободное время в день → какие мастера свободны (по порядку из salon.toml)."""
    masters = candidates(salon, service, master)
    busy = await db.busy(day)
    return free_slots_any(masters, day, service.minutes, busy,
                          salon.slot_step, now + salon.min_before)
