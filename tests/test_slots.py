"""Расчёт свободного времени — главная логика бота."""
from datetime import date, datetime, time

from bot.salon import Master
from bot.slots import booking_days, free_slots, free_slots_any, overlaps

MONDAY = date(2026, 11, 2)
SUNDAY = date(2026, 11, 8)
EARLY = datetime(2026, 1, 1)  # «сейчас» задолго до дня записи — ограничение не мешает


def master(name="Алексей", start=time(10), end=time(13), breaks=(), weekdays=range(5)):
    return Master(name, ("Стрижка",), frozenset(weekdays), start, end, tuple(breaks))


def at(hour, minute=0, day=MONDAY):
    return datetime.combine(day, time(hour, minute))


def hours(slots):
    return [s.strftime("%H:%M") for s in slots]


def test_overlaps_touching_is_not_overlap():
    assert not overlaps(at(10), at(11), at(11), at(12))
    assert overlaps(at(10), at(11, 30), at(11), at(12))
    assert overlaps(at(10), at(13), at(11), at(12))  # одна внутри другой


def test_whole_day_free():
    slots = free_slots(master(), MONDAY, 60, [], 30, EARLY)
    # последняя запись на час — в 12:00, чтобы закончить к 13:00
    assert hours(slots) == ["10:00", "10:30", "11:00", "11:30", "12:00"]


def test_day_off():
    assert free_slots(master(), SUNDAY, 60, [], 30, EARLY) == []


def test_break_is_skipped():
    m = master(end=time(15), breaks=[(time(12), time(13))])
    slots = hours(free_slots(m, MONDAY, 60, [], 30, EARLY))
    assert "11:00" in slots           # 11:00–12:00 — ровно до перерыва
    assert "11:30" not in slots       # залезло бы на перерыв
    assert "12:00" not in slots and "12:30" not in slots
    assert "13:00" in slots           # сразу после перерыва


def test_busy_booking_is_skipped():
    busy = [(at(11), at(12))]
    slots = hours(free_slots(master(), MONDAY, 60, busy, 30, EARLY))
    assert slots == ["10:00", "12:00"]  # 10:30 и 11:30 пересекаются с записью


def test_short_service_fits_between_bookings():
    busy = [(at(10), at(10, 30)), (at(11), at(13))]
    assert hours(free_slots(master(), MONDAY, 30, busy, 30, EARLY)) == ["10:30"]


def test_earliest_cuts_past_time():
    # сейчас 10:40 — на 10:00 и 10:30 уже поздно
    slots = hours(free_slots(master(), MONDAY, 60, [], 30, at(10, 40)))
    assert slots == ["11:00", "11:30", "12:00"]


def test_grid_starts_from_work_start():
    m = master(start=time(10, 15), end=time(12, 15))
    assert hours(free_slots(m, MONDAY, 60, [], 30, EARLY)) == ["10:15", "10:45", "11:15"]


def test_service_longer_than_day():
    assert free_slots(master(), MONDAY, 240, [], 30, EARLY) == []


def test_any_master_merges_and_sorts():
    anna = master("Анна", start=time(10), end=time(11))
    boris = master("Борис", start=time(10, 30), end=time(11, 30))
    busy = {"Анна": [(at(10), at(10, 30))]}
    result = free_slots_any([anna, boris], MONDAY, 30, busy, 30, EARLY)
    assert {k.strftime("%H:%M"): v for k, v in result.items()} == {
        "10:30": ["Анна", "Борис"],
        "11:00": ["Борис"],
    }
    assert list(result) == sorted(result)


def test_booking_days():
    days = booking_days(MONDAY, 3)
    assert days == [MONDAY, date(2026, 11, 3), date(2026, 11, 4)]
