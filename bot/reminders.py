"""Напоминания о визите (за 24 ч и за 2 ч — настраивается в salon.toml).

Раз в минуту бот смотрит в базу, кому пора напомнить, отправляет и ставит
отметку в столбце reminded. Отметки в базе, а не в памяти, поэтому после
перезапуска бот не напомнит повторно и не забудет тех, кому ещё не напомнил.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from .db import Booking
from .texts import booking_card, can_cancel

log = logging.getLogger(__name__)

CHECK_EVERY = 60  # секунд между проверками


def plan(booking: Booking, now: datetime, hours: tuple[int, ...]) -> tuple[int | None, set[int]]:
    """Что сделать с записью сейчас: (за сколько часов напомнить или None, что отметить).

    Правила:
    - напоминание за h часов «созрело», когда до начала осталось не больше h;
    - если созрело сразу несколько (бот был выключен или записались поздно),
      шлём только ближайшее, остальные отмечаем молча — одно сообщение, не три;
    - если запись сделали уже после момента напоминания (записались за 5 ч —
      «за 24 ч» опоздало), это напоминание не шлём: клиент только что получил
      подтверждение.
    """
    if not booking.active or booking.starts_at <= now:
        return None, set()
    left = booking.starts_at - now
    due = [h for h in hours if h not in booking.reminded and left <= timedelta(hours=h)]
    if not due:
        return None, set()
    nearest = min(due)
    made_in_time = booking.created_at <= booking.starts_at - timedelta(hours=nearest)
    return (nearest if made_in_time else None), set(due)


def relative_time(moment: datetime, now: datetime) -> str:
    """'сегодня в 14:30', 'завтра в 10:00' или '6 ноября в 12:00'."""
    from .texts import MONTHS
    days = (moment.date() - now.date()).days
    if days == 0:
        return f"сегодня в {moment:%H:%M}"
    if days == 1:
        return f"завтра в {moment:%H:%M}"
    return f"{moment.day} {MONTHS[moment.month - 1]} в {moment:%H:%M}"


def reminder_text(booking: Booking, now: datetime, address: str,
                  late_phone: str | None = None) -> str:
    """late_phone — телефон салона, если отменить через бота уже поздно."""
    text = (f"⏰ <b>Напоминаем: вы записаны {relative_time(booking.starts_at, now)}</b>\n\n"
            + booking_card(booking))
    if address:
        text += f"\n📍 {html.escape(address)}"
    text += "\n\nЖдём вас!"
    if late_phone:
        text += f" Если не получается прийти — позвоните: {html.escape(late_phone)}"
    return text


async def send_due(bot, db, config) -> int:
    """Один проход: отправить созревшие напоминания. Возвращает, сколько отправлено."""
    from .my_bookings import cancel_button_kb  # aiogram нужен только здесь

    salon = config.salon
    if not salon.reminders:
        return 0
    now = config.now()
    bookings = await db.upcoming(now, now + timedelta(hours=max(salon.reminders)))
    sent = 0
    for booking in bookings:
        hour, mark = plan(booking, now, salon.reminders)
        if not mark:
            continue
        if hour is not None:
            # Кнопка отмены — только пока клиент может отменить сам (cancel_hours_before),
            # позже вместо неё — телефон салона
            cancellable = can_cancel(booking, now, salon.cancel_before)
            kb = cancel_button_kb(booking) if cancellable else None
            text = reminder_text(booking, now, salon.address,
                                 late_phone=None if cancellable else salon.phone)
            try:
                await bot.send_message(booking.user_id, text, reply_markup=kb)
                sent += 1
            except Exception:
                # Клиент заблокировал бота и т.п. — отметку всё равно ставим, иначе
                # бот будет пытаться каждую минуту
                log.exception("Не удалось отправить напоминание по записи №%s", booking.id)
            await asyncio.sleep(0.05)  # Telegram ограничивает частоту сообщений
        await db.mark_reminded(booking.id, mark)
    return sent


async def reminders_loop(bot, db, config) -> None:
    """Фоновая задача: проверка раз в минуту, пока работает бот."""
    while True:
        try:
            sent = await send_due(bot, db, config)
            if sent:
                log.info("Отправлено напоминаний: %d", sent)
        except Exception:
            # Ошибка одного прохода не должна останавливать напоминания насовсем
            log.exception("Ошибка при отправке напоминаний")
        await asyncio.sleep(CHECK_EVERY)
