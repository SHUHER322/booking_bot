"""Когда и какие напоминания отправлять."""
import asyncio
from datetime import datetime, timedelta

import pytest

from bot.db import Booking, Client, Database
from bot.reminders import plan, relative_time, reminder_text

START = datetime(2026, 11, 5, 14, 0)
HOURS = (24, 2)


def booking(created=START - timedelta(days=3), reminded=(), status="active"):
    return Booking(1, 1, "Иван", "+7", None, "Алексей", "Стрижка", 1200, START,
                   START + timedelta(hours=1), status, None, tuple(reminded), created)


def before(hours, minutes=0):
    return START - timedelta(hours=hours, minutes=minutes)


def test_too_early_nothing():
    assert plan(booking(), before(30), HOURS) == (None, set())


def test_day_reminder():
    assert plan(booking(), before(24), HOURS) == (24, {24})
    assert plan(booking(), before(23, 59), HOURS) == (24, {24})


def test_day_already_sent_then_two_hours():
    b = booking(reminded=(24,))
    assert plan(b, before(10), HOURS) == (None, set())
    assert plan(b, before(2), HOURS) == (2, {2})


def test_both_due_sends_only_nearest():
    # бот был выключен сутки: созрели оба — одно сообщение, отмечаем оба
    assert plan(booking(), before(1), HOURS) == (2, {24, 2})


def test_booked_late_skips_day_reminder():
    # записались за 5 часов: «за 24 ч» не шлём, но отмечаем; «за 2 ч» потом придёт
    b = booking(created=before(5))
    assert plan(b, before(5), HOURS) == (None, {24})
    b = booking(created=before(5), reminded=(24,))
    assert plan(b, before(2), HOURS) == (2, {2})


def test_booked_very_late_no_reminders():
    b = booking(created=before(1))
    assert plan(b, before(1), HOURS) == (None, {24, 2})


@pytest.mark.parametrize("b, now", [
    (booking(status="cancelled"), before(1)),
    (booking(), START),                 # уже началось
    (booking(reminded=(24, 2)), before(1)),
])
def test_nothing_to_do(b, now):
    assert plan(b, now, HOURS) == (None, set())


def test_relative_time():
    assert relative_time(START, datetime(2026, 11, 5, 9, 0)) == "сегодня в 14:00"
    assert relative_time(START, datetime(2026, 11, 4, 20, 0)) == "завтра в 14:00"
    assert relative_time(START, datetime(2026, 11, 1, 9, 0)) == "5 ноября в 14:00"


def test_reminder_text():
    text = reminder_text(booking(), before(2), "пр. Ленина, 1")
    assert "сегодня в 14:00" in text and "Стрижка" in text and "пр. Ленина, 1" in text


def test_db_upcoming_and_mark(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    asyncio.run(db.init())
    client = Client(1, "Иван", "+7", None)
    now = datetime(2026, 11, 4, 12, 0)
    soon = asyncio.run(db.add_booking(client, "Алексей", "Стрижка", 1200, START,
                                      START + timedelta(hours=1), now))
    later = START + timedelta(days=5)
    asyncio.run(db.add_booking(client, "Алексей", "Стрижка", 1200, later,
                               later + timedelta(hours=1), now))
    found = asyncio.run(db.upcoming(now, now + timedelta(hours=48)))
    assert [b.id for b in found] == [soon.id]
    asyncio.run(db.mark_reminded(soon.id, {24}))
    asyncio.run(db.mark_reminded(soon.id, {2}))
    assert asyncio.run(db.get_booking(soon.id)).reminded == (24, 2)
