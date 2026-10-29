"""Расписание на день для админа."""
from datetime import date, datetime, time, timedelta

from bot.db import Booking
from bot.salon import Master, Salon, Service
from bot.schedule import build_schedule

MONDAY = date(2026, 11, 2)
ANNA = Master("Анна", ("Стрижка",), frozenset({0}), time(10), time(19))
BORIS = Master("Борис", ("Стрижка",), frozenset({5}), time(11), time(20))   # только сб
SALON = Salon("Тест", "", 30, 14, timedelta(hours=1), timedelta(hours=3), (24, 2),
              (Service("Стрижка", 60, 1200),), (ANNA, BORIS))


def booking(id_, master, hour, price=1200, username="ivan"):
    start = datetime.combine(MONDAY, time(hour))
    return Booking(id_, 1, "Иван", "+7 913", username, master, "Стрижка", price,
                   start, start + timedelta(hours=1), "active", None, (), start)


def test_empty_day():
    text = build_schedule(MONDAY, [], SALON)
    assert "понедельник, 2 ноября" in text
    assert "Анна</b> · 10:00–19:00\nзаписей нет" in text
    assert "Борис</b> — выходной" in text
    assert "Итого" not in text


def test_bookings_sorted_with_total():
    text = build_schedule(MONDAY, [booking(2, "Анна", 15), booking(1, "Анна", 11, 700)], SALON)
    assert text.index("11:00–12:00") < text.index("15:00–16:00")
    assert "Иван, +7 913, @ivan" in text
    assert "Итого: <b>2</b> зап. на 1 900 ₽" in text


def test_removed_master_still_shown():
    text = build_schedule(MONDAY, [booking(1, "Уволенный", 12)], SALON)
    assert "Уволенный" in text and "12:00–13:00" in text


def test_html_escaped():
    b = booking(1, "Анна", 12, username=None)
    b = Booking(**{**b.__dict__, "client_name": "<b>Хакер</b>"})
    text = build_schedule(MONDAY, [b], SALON)
    assert "&lt;b&gt;Хакер&lt;/b&gt;" in text and "@" not in text
