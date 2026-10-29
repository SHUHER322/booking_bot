"""Свободные дни и время с учётом записей в базе."""
import asyncio
from datetime import date, datetime, time, timedelta

import pytest

from bot.availability import candidates, free_days, free_times
from bot.db import Client, Database
from bot.salon import Master, Salon, Service

CUT = Service("Стрижка", 60, 1000)
BEARD = Service("Борода", 60, 500)
ANNA = Master("Анна", ("Стрижка",), frozenset({0}), time(10), time(12))          # только пн
BORIS = Master("Борис", ("Стрижка", "Борода"), frozenset({0, 1}), time(10), time(12))
SALON = Salon("Тест", "", 60, 7, timedelta(hours=1), timedelta(hours=3), (24, 2),
              (CUT, BEARD), (ANNA, BORIS))
NOW = datetime(2026, 11, 1, 12, 0)   # воскресенье
MONDAY = date(2026, 11, 2)
IVAN = Client(1, "Иван", "+7 913 000-00-00", None)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    asyncio.run(database.init())
    return database


def book(db, master, hour):
    start = datetime.combine(MONDAY, time(hour))
    return asyncio.run(db.add_booking(IVAN, master, "Стрижка", 1000, start,
                                      start + timedelta(hours=1), NOW))


def test_candidates():
    assert candidates(SALON, CUT, None) == (ANNA, BORIS)
    assert candidates(SALON, BEARD, None) == (BORIS,)
    assert candidates(SALON, CUT, "Анна") == (ANNA,)
    assert candidates(SALON, BEARD, "Анна") == ()   # Анна бороду не делает
    assert candidates(SALON, CUT, "Нет такого") == ()


def test_free_days(db):
    days = asyncio.run(free_days(db, SALON, CUT, None, NOW))
    assert days == [MONDAY, date(2026, 11, 3)]       # пн — оба, вт — Борис
    assert asyncio.run(free_days(db, SALON, CUT, "Анна", NOW)) == [MONDAY]


def test_fully_booked_day_disappears(db):
    for hour in (10, 11):
        book(db, "Анна", hour)
    assert asyncio.run(free_days(db, SALON, CUT, "Анна", NOW)) == []
    assert MONDAY in asyncio.run(free_days(db, SALON, CUT, None, NOW))  # у Бориса свободно


def test_free_times_any_master(db):
    book(db, "Анна", 10)
    times = asyncio.run(free_times(db, SALON, CUT, None, MONDAY, NOW))
    assert {t.strftime("%H:%M"): v for t, v in times.items()} == {
        "10:00": ["Борис"], "11:00": ["Анна", "Борис"]}
