"""База записей (SQLite).

Используется стандартный sqlite3, а запросы уходят в отдельный поток через
asyncio.to_thread — так бот не «замирает», пока идёт обращение к диску.
Время хранится строкой «ГГГГ-ММ-ДД ЧЧ:ММ» по местному времени салона:
такие строки правильно сравниваются и сортируются как текст.
"""
import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .slots import Interval, overlaps

FMT = "%Y-%m-%d %H:%M"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    user_id    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL,
    username   TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    client_name  TEXT NOT NULL,
    client_phone TEXT NOT NULL,
    username     TEXT,
    master       TEXT NOT NULL,
    service      TEXT NOT NULL,
    price        INTEGER NOT NULL,
    starts_at    TEXT NOT NULL,
    ends_at      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',   -- active | cancelled
    cancelled_by TEXT,                             -- client | admin
    reminded     TEXT NOT NULL DEFAULT '',         -- за сколько часов уже напомнили: "24,2"
    created_at   TEXT NOT NULL,
    cancel_reason TEXT                             -- причина отмены салоном (если указали)
);
CREATE INDEX IF NOT EXISTS bookings_master_time ON bookings (master, starts_at);
CREATE INDEX IF NOT EXISTS bookings_user ON bookings (user_id, starts_at);
"""

BOOKING_COLUMNS = ("id, user_id, client_name, client_phone, username, master, service, "
                   "price, starts_at, ends_at, status, cancelled_by, reminded, created_at, "
                   "cancel_reason")


def to_text(moment: datetime) -> str:
    return moment.strftime(FMT)


def from_text(value: str) -> datetime:
    return datetime.strptime(value, FMT)


@dataclass(frozen=True)
class Client:
    user_id: int
    name: str
    phone: str
    username: str | None


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    client_name: str
    client_phone: str
    username: str | None
    master: str
    service: str
    price: int
    starts_at: datetime
    ends_at: datetime
    status: str
    cancelled_by: str | None
    reminded: tuple[int, ...]
    created_at: datetime
    cancel_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


def _booking(row: tuple) -> Booking:
    (id_, user_id, name, phone, username, master, service, price,
     starts, ends, status, cancelled_by, reminded, created, reason) = row
    return Booking(id_, user_id, name, phone, username, master, service, price,
                   from_text(starts), from_text(ends), status, cancelled_by,
                   tuple(int(h) for h in reminded.split(",") if h), from_text(created), reason)


class Database:
    def __init__(self, path: str):
        self.path = path

    def _open(self) -> sqlite3.Connection:
        # timeout — сколько ждать, если базу в этот момент пишет другой запрос
        return sqlite3.connect(self.path, timeout=10)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Соединение на один запрос: при успехе — commit, при ошибке — rollback,
        в конце всегда закрывается (сам по себе `with sqlite3.connect()` не закрывает)."""
        db = self._open()
        try:
            with db:
                yield db
        finally:
            db.close()

    async def _run(self, func, *args):
        return await asyncio.to_thread(func, *args)

    # --- создание ---

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript(SCHEMA)
            # Миграция: в базах, созданных до появления причины отмены, нет этого столбца
            columns = {row[1] for row in db.execute("PRAGMA table_info(bookings)")}
            if "cancel_reason" not in columns:
                db.execute("ALTER TABLE bookings ADD COLUMN cancel_reason TEXT")

    async def init(self) -> None:
        await self._run(self._init)

    # --- клиенты: имя и телефон запоминаем, чтобы не спрашивать каждый раз ---

    def _get_client(self, user_id: int) -> Client | None:
        with self._connect() as db:
            row = db.execute("SELECT user_id, name, phone, username FROM clients "
                             "WHERE user_id = ?", (user_id,)).fetchone()
        return Client(*row) if row else None

    async def get_client(self, user_id: int) -> Client | None:
        return await self._run(self._get_client, user_id)

    def _save_client(self, client: Client) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO clients (user_id, name, phone, username) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, "
                       "phone = excluded.phone, username = excluded.username",
                       (client.user_id, client.name, client.phone, client.username))

    async def save_client(self, client: Client) -> None:
        await self._run(self._save_client, client)

    # --- занятость ---

    def _busy(self, day: date) -> dict[str, list[Interval]]:
        day_start = to_text(datetime.combine(day, datetime.min.time()))
        day_end = to_text(datetime.combine(day + timedelta(days=1), datetime.min.time()))
        with self._connect() as db:
            rows = db.execute("SELECT master, starts_at, ends_at FROM bookings "
                              "WHERE status = 'active' AND starts_at >= ? AND starts_at < ?",
                              (day_start, day_end)).fetchall()
        busy: dict[str, list[Interval]] = {}
        for master, starts, ends in rows:
            busy.setdefault(master, []).append((from_text(starts), from_text(ends)))
        return busy

    async def busy(self, day: date) -> dict[str, list[Interval]]:
        """Занятые промежутки за день по мастерам: {"Алексей": [(10:00, 11:00), …]}."""
        return await self._run(self._busy, day)

    def _busy_between(self, first: date, last: date) -> dict[date, dict[str, list[Interval]]]:
        start = to_text(datetime.combine(first, datetime.min.time()))
        end = to_text(datetime.combine(last + timedelta(days=1), datetime.min.time()))
        with self._connect() as db:
            rows = db.execute("SELECT master, starts_at, ends_at FROM bookings "
                              "WHERE status = 'active' AND starts_at >= ? AND starts_at < ?",
                              (start, end)).fetchall()
        result: dict[date, dict[str, list[Interval]]] = {}
        for master, starts, ends in rows:
            begin = from_text(starts)
            result.setdefault(begin.date(), {}).setdefault(master, []).append(
                (begin, from_text(ends)))
        return result

    async def busy_between(self, first: date, last: date) -> dict[date, dict[str, list[Interval]]]:
        """То же, что busy, но сразу за несколько дней — одним запросом к базе."""
        return await self._run(self._busy_between, first, last)

    # --- записи ---

    def _add_booking(self, client: Client, master: str, service: str, price: int,
                     starts_at: datetime, ends_at: datetime, now: datetime) -> Booking | None:
        db = self._open()
        try:
            # BEGIN IMMEDIATE сразу блокирует базу на запись: между проверкой
            # «время свободно» и сохранением никто другой не успеет вклиниться
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT starts_at, ends_at FROM bookings "
                              "WHERE status = 'active' AND master = ? "
                              "AND starts_at < ? AND ends_at > ?",
                              (master, to_text(ends_at), to_text(starts_at))).fetchall()
            if any(overlaps(starts_at, ends_at, from_text(s), from_text(e)) for s, e in rows):
                db.rollback()
                return None
            cursor = db.execute(
                "INSERT INTO bookings (user_id, client_name, client_phone, username, master, "
                "service, price, starts_at, ends_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (client.user_id, client.name, client.phone, client.username, master, service,
                 price, to_text(starts_at), to_text(ends_at), to_text(now)))
            booking_id = cursor.lastrowid
            db.commit()
        finally:
            db.close()
        return self._get_booking(booking_id)

    async def add_booking(self, client: Client, master: str, service: str, price: int,
                          starts_at: datetime, ends_at: datetime,
                          now: datetime) -> Booking | None:
        """Сохраняет запись. None — если это время у мастера уже заняли."""
        return await self._run(self._add_booking, client, master, service, price,
                               starts_at, ends_at, now)

    def _get_booking(self, booking_id: int) -> Booking | None:
        with self._connect() as db:
            row = db.execute(f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE id = ?",
                             (booking_id,)).fetchone()
        return _booking(row) if row else None

    async def get_booking(self, booking_id: int) -> Booking | None:
        return await self._run(self._get_booking, booking_id)

    def _user_bookings(self, user_id: int, now: datetime) -> list[Booking]:
        with self._connect() as db:
            rows = db.execute(f"SELECT {BOOKING_COLUMNS} FROM bookings "
                              "WHERE user_id = ? AND status = 'active' AND starts_at >= ? "
                              "ORDER BY starts_at", (user_id, to_text(now))).fetchall()
        return [_booking(r) for r in rows]

    async def user_bookings(self, user_id: int, now: datetime) -> list[Booking]:
        """Предстоящие активные записи клиента."""
        return await self._run(self._user_bookings, user_id, now)

    def _day_bookings(self, day: date) -> list[Booking]:
        with self._connect() as db:
            rows = db.execute(f"SELECT {BOOKING_COLUMNS} FROM bookings "
                              "WHERE status = 'active' AND starts_at LIKE ? "
                              "ORDER BY master, starts_at", (f"{day.isoformat()}%",)).fetchall()
        return [_booking(r) for r in rows]

    async def day_bookings(self, day: date) -> list[Booking]:
        """Активные записи на день — для расписания админа."""
        return await self._run(self._day_bookings, day)

    def _cancel(self, booking_id: int, by: str, reason: str | None) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE bookings SET status = 'cancelled', cancelled_by = ?, "
                                "cancel_reason = ? WHERE id = ? AND status = 'active'",
                                (by, reason, booking_id))
            return cursor.rowcount == 1

    async def cancel(self, booking_id: int, by: str, reason: str | None = None) -> bool:
        """Отменяет запись. False — если её уже отменили раньше."""
        return await self._run(self._cancel, booking_id, by, reason)
