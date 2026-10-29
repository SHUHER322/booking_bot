"""База: запись, защита от двойной записи, отмена, занятость."""
import asyncio
from datetime import date, datetime

import pytest

from bot.db import Client, Database

NOW = datetime(2026, 11, 1, 12, 0)
DAY = date(2026, 11, 2)
IVAN = Client(1, "Иван", "+7 913 000-00-00", "ivan")


def at(hour, minute=0):
    return datetime(2026, 11, 2, hour, minute)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    asyncio.run(database.init())
    return database


def book(db, start, end, master="Алексей", client=IVAN):
    return asyncio.run(db.add_booking(client, master, "Стрижка", 1200, start, end, NOW))


def test_client_saved_and_updated(db):
    assert asyncio.run(db.get_client(1)) is None
    asyncio.run(db.save_client(IVAN))
    asyncio.run(db.save_client(Client(1, "Иван Петров", "+7 913 111-11-11", None)))
    assert asyncio.run(db.get_client(1)) == Client(1, "Иван Петров", "+7 913 111-11-11", None)


def test_add_booking_returns_booking(db):
    booking = book(db, at(10), at(11))
    assert booking.id == 1 and booking.active
    assert (booking.starts_at, booking.ends_at) == (at(10), at(11))
    assert booking.client_name == "Иван" and booking.reminded == ()
    assert booking.created_at == NOW


def test_overlapping_booking_rejected(db):
    assert book(db, at(10), at(11))
    assert book(db, at(10, 30), at(11, 30)) is None   # пересекается
    assert book(db, at(11), at(12))                   # встык — можно
    assert book(db, at(10), at(11), master="Денис")   # другой мастер — можно


def test_cancelled_slot_is_free_again(db):
    booking = book(db, at(10), at(11))
    assert asyncio.run(db.cancel(booking.id, "client"))
    assert not asyncio.run(db.cancel(booking.id, "client"))  # второй раз — уже нечего
    assert asyncio.run(db.get_booking(booking.id)).cancelled_by == "client"
    assert book(db, at(10), at(11))


def test_busy_by_master_for_day(db):
    book(db, at(10), at(11))
    book(db, at(12), at(13), master="Денис")
    book(db, datetime(2026, 11, 3, 10), datetime(2026, 11, 3, 11))  # другой день
    cancelled = book(db, at(15), at(16))
    asyncio.run(db.cancel(cancelled.id, "admin"))
    assert asyncio.run(db.busy(DAY)) == {"Алексей": [(at(10), at(11))],
                                         "Денис": [(at(12), at(13))]}


def test_user_and_day_bookings(db):
    past = book(db, datetime(2026, 11, 1, 10), datetime(2026, 11, 1, 11))
    late = book(db, at(15), at(16))
    early = book(db, at(10), at(11))
    other = book(db, at(12), at(13), client=Client(2, "Пётр", "+7 900 000-00-00", None))
    assert [b.id for b in asyncio.run(db.user_bookings(1, NOW))] == [early.id, late.id]
    assert past.id not in [b.id for b in asyncio.run(db.user_bookings(1, NOW))]
    assert [b.id for b in asyncio.run(db.day_bookings(DAY))] == [early.id, other.id, late.id]
