"""Админ: расписание на день (/today, /tomorrow) и отмена записи с уведомлением клиенту."""
import html
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Config
from .db import Booking, Database
from .keyboards import BTN_BOOK, BTN_CANCEL, BTN_MY, cancel_kb, main_kb
from .notify import send_to_admins
from .schedule import build_schedule
from .states import AdminCancel
from .texts import admin_card, booking_card

router = Router()
MENU_BUTTONS = {BTN_BOOK, BTN_MY, BTN_CANCEL}
log = logging.getLogger(__name__)

DAY = "adm:day:"       # adm:day:20261102  — расписание на день
LIST = "adm:list:"     # adm:list:20261102 — выбрать запись для отмены
ASK = "adm:ask:"       # adm:ask:<id>
YES = "adm:yes:"       # adm:yes:<id>:<номер причины> или adm:yes:<id>:- (без причины)
OWN = "adm:own:"       # adm:own:<id>  — админ напишет причину сам


def is_admin(event: Message | CallbackQuery, config: Config) -> bool:
    """Фильтр: команды и кнопки админа доступны только из ADMIN_CHAT_ID."""
    return event.from_user.id in config.admin_chat_ids


router.message.filter(is_admin)
router.callback_query.filter(is_admin)


def _day(data: str, prefix: str) -> date:
    return datetime.strptime(data.removeprefix(prefix), "%Y%m%d").date()


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def schedule_kb(day: date, today: date, has_bookings: bool) -> InlineKeyboardMarkup:
    prev, next_ = day - timedelta(days=1), day + timedelta(days=1)
    rows = [[_button(f"◀️ {prev:%d.%m}", f"{DAY}{prev:%Y%m%d}"),
             _button("Сегодня", f"{DAY}{today:%Y%m%d}"),
             _button(f"{next_:%d.%m} ▶️", f"{DAY}{next_:%Y%m%d}")]]
    if has_bookings:
        rows.append([_button("❌ Отменить запись…", f"{LIST}{day:%Y%m%d}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def schedule_view(day: date, db: Database, config: Config) -> tuple[str, InlineKeyboardMarkup]:
    bookings = await db.day_bookings(day)
    text = build_schedule(day, bookings, config.salon)
    return text, schedule_kb(day, config.now().date(), bool(bookings))


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup,
                answer: bool = True) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):  # повторное нажатие «Сегодня»
            raise
    if answer:  # на одно нажатие Telegram принимает только один ответ
        await callback.answer()


@router.message(Command("today"))
async def today(message: Message, db: Database, config: Config):
    text, kb = await schedule_view(config.now().date(), db, config)
    await message.answer(text, reply_markup=kb)


@router.message(Command("tomorrow"))
async def tomorrow(message: Message, db: Database, config: Config):
    text, kb = await schedule_view(config.now().date() + timedelta(days=1), db, config)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith(DAY))
async def show_day(callback: CallbackQuery, db: Database, config: Config):
    await _edit(callback, *await schedule_view(_day(callback.data, DAY), db, config))


@router.callback_query(F.data.startswith(LIST))
async def choose_booking(callback: CallbackQuery, db: Database, config: Config):
    day = _day(callback.data, LIST)
    bookings = await db.day_bookings(day)
    rows = [[_button(f"❌ {b.starts_at:%H:%M} {b.master} · {b.client_name}", f"{ASK}{b.id}")]
            for b in bookings]
    rows.append([_button("⬅️ К расписанию", f"{DAY}{day:%Y%m%d}")])
    await _edit(callback, "Какую запись отменить?", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(ASK))
async def ask_cancel(callback: CallbackQuery, db: Database, config: Config):
    booking = await db.get_booking(int(callback.data.removeprefix(ASK)))
    if not booking or not booking.active:
        await callback.answer("Запись уже отменена", show_alert=True)
        return
    # В callback_data — номер причины, а не текст: лимит 64 байта
    rows = [[_button(reason, f"{YES}{booking.id}:{i}")]
            for i, reason in enumerate(config.salon.cancel_reasons)]
    rows += [[_button("✍️ Написать свою причину", f"{OWN}{booking.id}")],
             [_button("Без причины", f"{YES}{booking.id}:-")],
             [_button("⬅️ Не отменять", f"{LIST}{booking.starts_at:%Y%m%d}")]]
    await _edit(callback, admin_card(booking, "Отменить запись") +
                "\n\nВыберите причину — клиент увидит её в уведомлении.",
                InlineKeyboardMarkup(inline_keyboard=rows))


async def cancel_booking(bot: Bot, db: Database, config: Config, booking: Booking,
                         reason: str | None, admin_id: int) -> str | None:
    """Отменяет запись, уведомляет клиента и других админов.
    Возвращает пометку для админа или None, если запись уже отменили."""
    if not await db.cancel(booking.id, "admin", reason):
        return None
    text = "😔 <b>Ваша запись отменена салоном</b>\n\n" + booking_card(booking)
    if reason:
        text += f"\n\nПричина: {html.escape(reason)}"
    text += f"\n\nПриносим извинения. Выбрать другое время — «{BTN_BOOK}»."
    try:
        await bot.send_message(booking.user_id, text)
        note = "Клиент уведомлён."
    except Exception:
        # Например, клиент заблокировал бота — тогда звонить по телефону
        log.exception("Не удалось уведомить клиента %s об отмене", booking.user_id)
        note = f"⚠️ Клиенту не дошло сообщение — позвоните: {html.escape(booking.client_phone)}"
    # Остальные админы тоже должны знать, что время освободилось
    others = tuple(i for i in config.admin_chat_ids if i != admin_id)
    if others:
        card = admin_card(booking, "❌ <b>Админ отменил запись</b>")
        if reason:
            card += f"\nПричина: {html.escape(reason)}"
        await send_to_admins(bot, others, card)
    return note


@router.callback_query(F.data.startswith(YES))
async def cancel_with_reason(callback: CallbackQuery, bot: Bot, db: Database, config: Config):
    booking_id, _, choice = callback.data.removeprefix(YES).partition(":")
    reasons = config.salon.cancel_reasons
    if choice.isdigit() and int(choice) < len(reasons):
        reason = reasons[int(choice)]
    elif choice == "-":
        reason = None
    else:  # список причин поменяли, а кнопка осталась старая
        await callback.answer("Эта кнопка устарела, откройте отмену заново", show_alert=True)
        return
    booking = await db.get_booking(int(booking_id))
    note = booking and await cancel_booking(bot, db, config, booking, reason, callback.from_user.id)
    if not note:
        await callback.answer("Запись уже отменена", show_alert=True)
        return
    await callback.answer("Запись отменена")
    text, kb = await schedule_view(booking.starts_at.date(), db, config)
    await _edit(callback, f"✅ Запись №{booking.id} отменена. {note}\n\n{text}", kb, answer=False)


@router.callback_query(F.data.startswith(OWN))
async def ask_own_reason(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCancel.reason)
    await state.update_data(cancel_id=int(callback.data.removeprefix(OWN)))
    await callback.answer()
    await callback.message.answer("Напишите причину одним сообщением — её получит клиент.\n"
                                  "Например: «Отключили воду, приносим извинения».",
                                  reply_markup=cancel_kb)


# Кнопки меню и команды не считаем причиной — их обработают в общем роутере
@router.message(AdminCancel.reason, F.text, ~F.text.in_(MENU_BUTTONS), ~F.text.startswith("/"))
async def own_reason(message: Message, state: FSMContext, bot: Bot, db: Database, config: Config):
    reason = message.text.strip()
    if not 2 <= len(reason) <= 300:
        await message.answer("Причина — от 2 до 300 символов.")
        return
    booking_id = (await state.get_data()).get("cancel_id")
    await state.clear()
    booking = await db.get_booking(booking_id) if booking_id else None
    note = booking and await cancel_booking(bot, db, config, booking, reason, message.from_user.id)
    if not note:
        await message.answer("Эта запись уже отменена.", reply_markup=main_kb())
        return
    await message.answer(f"✅ Запись №{booking.id} отменена. {note}", reply_markup=main_kb())
    text, kb = await schedule_view(booking.starts_at.date(), db, config)
    await message.answer(text, reply_markup=kb)
