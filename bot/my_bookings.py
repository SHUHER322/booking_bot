"""«Мои записи»: список предстоящих записей клиента и отмена."""
import html
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, or_f
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Config
from .db import Booking, Database
from .keyboards import BTN_BOOK, BTN_MY, main_kb
from .notify import send_to_admins
from .texts import admin_card, booking_card, can_cancel, hours_text, when

router = Router()

ASK_CANCEL = "my:ask:"     # my:ask:<id>  — «Отменить?»
DO_CANCEL = "my:yes:"      # my:yes:<id>  — да, отменить
MY_LIST = "my:list"        # назад к списку


def my_list(bookings: list[Booking], now: datetime, config: Config) -> tuple[str, InlineKeyboardMarkup | None]:
    """Текст списка и кнопки отмены для тех записей, которые ещё можно отменить."""
    salon = config.salon
    if not bookings:
        return f"У вас нет предстоящих записей.\nЗаписаться — «{BTN_BOOK}».", None
    parts, buttons, late = [], [], False
    for b in bookings:
        parts.append(booking_card(b) + f"\n🙋 {html.escape(b.client_name)}")
        if can_cancel(b, now, salon.cancel_before):
            buttons.append([InlineKeyboardButton(
                text=f"❌ Отменить {b.starts_at:%d.%m %H:%M}", callback_data=f"{ASK_CANCEL}{b.id}")])
        else:
            late = True
    text = "<b>Ваши записи</b>\n\n" + "\n\n".join(parts)
    if late:
        text += (f"\n\nОтменить через бота можно не позже чем за {hours_text(salon.cancel_before)} "
                 "до начала.")
        if salon.phone:
            text += f" Позже — по телефону {html.escape(salon.phone)}."
    return text, InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


async def _own_booking(callback: CallbackQuery, db: Database, prefix: str) -> Booking | None:
    """Запись по кнопке — только если она принадлежит этому клиенту."""
    try:
        booking_id = int(callback.data.removeprefix(prefix))
    except ValueError:
        return None
    booking = await db.get_booking(booking_id)
    return booking if booking and booking.user_id == callback.from_user.id else None


async def _show_list(callback: CallbackQuery, db: Database, config: Config, note: str = "") -> None:
    now = config.now()
    text, kb = my_list(await db.user_bookings(callback.from_user.id, now), now, config)
    await callback.message.edit_text((note + "\n\n" if note else "") + text, reply_markup=kb)


@router.message(or_f(Command("my"), F.text == BTN_MY))
async def my_bookings(message: Message, db: Database, config: Config):
    now = config.now()
    text, kb = my_list(await db.user_bookings(message.from_user.id, now), now, config)
    await message.answer(text, reply_markup=kb or main_kb())


@router.callback_query(F.data.startswith(ASK_CANCEL))
async def ask_cancel(callback: CallbackQuery, db: Database, config: Config):
    booking = await _own_booking(callback, db, ASK_CANCEL)
    if not booking or not can_cancel(booking, config.now(), config.salon.cancel_before):
        await callback.answer("Эту запись уже нельзя отменить через бота.", show_alert=True)
        await _show_list(callback, db, config)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, отменить", callback_data=f"{DO_CANCEL}{booking.id}"),
         InlineKeyboardButton(text="Нет, оставить", callback_data=MY_LIST)],
    ])
    await callback.message.edit_text("Отменить запись?\n\n" + booking_card(booking), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith(DO_CANCEL))
async def do_cancel(callback: CallbackQuery, bot: Bot, db: Database, config: Config):
    booking = await _own_booking(callback, db, DO_CANCEL)
    # Проверяем ещё раз: пока клиент думал, время могло пройти или запись отменил админ
    if not booking or not can_cancel(booking, config.now(), config.salon.cancel_before) \
            or not await db.cancel(booking.id, "client"):
        await callback.answer("Эту запись уже нельзя отменить через бота.", show_alert=True)
        await _show_list(callback, db, config)
        return
    await callback.answer("Запись отменена")
    await _show_list(callback, db, config,
                     note=f"✅ Запись на {when(booking.starts_at)} отменена.")
    await send_to_admins(bot, config.admin_chat_ids,
                         admin_card(booking, "❌ <b>Клиент отменил запись</b>"))


@router.callback_query(F.data == MY_LIST)
async def back_to_list(callback: CallbackQuery, db: Database, config: Config):
    await _show_list(callback, db, config)
    await callback.answer()
