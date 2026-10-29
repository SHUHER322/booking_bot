"""Тексты и форматирование: даты по-русски, цены, карточка записи."""
import html
import re
from datetime import date, datetime, timedelta

from .db import Booking
from .salon import Service

WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря")

# Какие символы можно вводить. re.ASCII — чтобы \d был только 0–9
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{10,18}$", re.ASCII)


def is_valid_phone(phone: str) -> bool:
    """Номер в свободном формате, но с разумным количеством цифр."""
    if not PHONE_RE.match(phone):
        return False
    digits = sum(c.isdigit() for c in phone)
    return 10 <= digits <= 15


def rub(price: int) -> str:
    """1700 → '1 700 ₽' (неразрывный пробел, чтобы цена не переносилась)."""
    return f"{price:,}".replace(",", " ") + " ₽"


def duration(minutes: int) -> str:
    """90 → '1 ч 30 мин', 60 → '1 ч', 30 → '30 мин'."""
    hours, mins = divmod(minutes, 60)
    parts = ([f"{hours} ч"] if hours else []) + ([f"{mins} мин"] if mins else [])
    return " ".join(parts)


def service_button(service: Service) -> str:
    return f"{service.name} · {duration(service.minutes)} · {rub(service.price)}"


def day_button(day: date, today: date) -> str:
    """Кнопка дня: 'Сегодня', 'Завтра' или 'Пт 06.11'."""
    if day == today:
        return f"Сегодня {day:%d.%m}"
    if (day - today).days == 1:
        return f"Завтра {day:%d.%m}"
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m}"


def long_date(day: date) -> str:
    """'пятница, 6 ноября' — для подтверждения и напоминаний."""
    weekdays = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    return f"{weekdays[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def when(moment: datetime) -> str:
    """'пятница, 6 ноября, 14:30'"""
    return f"{long_date(moment.date())}, {moment:%H:%M}"


def summary(service: Service, master: str | None, moment: datetime | None = None) -> str:
    """Что уже выбрано — показываем над каждым следующим вопросом."""
    lines = [f"💈 <b>{html.escape(service.name)}</b> · {duration(service.minutes)} · {rub(service.price)}",
             f"👤 Мастер: {html.escape(master) if master else 'любой свободный'}"]
    if moment:
        lines.append(f"🗓 {when(moment)}")
    return "\n".join(lines)


def booking_card(b: Booking) -> str:
    """Карточка записи для клиента."""
    return (f"🗓 <b>{when(b.starts_at)}</b>\n"
            f"💈 {html.escape(b.service)} · {rub(b.price)}\n"
            f"👤 Мастер: {html.escape(b.master)}")


def admin_card(b: Booking, title: str) -> str:
    """Уведомление админу о записи или отмене."""
    username = f"@{b.username}" if b.username else "—"
    return (f"{title} №{b.id}\n"
            f"🗓 <b>{when(b.starts_at)}</b> – {b.ends_at:%H:%M}\n"
            f"💈 {html.escape(b.service)} · {rub(b.price)}\n"
            f"👤 Мастер: {html.escape(b.master)}\n"
            f"Клиент: {html.escape(b.client_name)}, {html.escape(b.client_phone)}\n"
            f"Telegram: {html.escape(username)}")


def can_cancel(booking: Booking, now: datetime, cancel_before: timedelta) -> bool:
    """Клиент может отменить сам, если до начала осталось не меньше cancel_before."""
    return booking.active and booking.starts_at - now >= cancel_before


def hours_text(delta: timedelta) -> str:
    """timedelta(hours=3) → '3 ч', 1.5 часа → '1.5 ч'."""
    return f"{delta.total_seconds() / 3600:g} ч"
