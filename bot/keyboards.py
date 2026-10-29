"""Кнопки: меню под полем ввода (reply) и шаги записи под сообщением (inline)."""
from datetime import date, datetime

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

from .salon import Master, Service
from .texts import day_button, service_button

# Тексты кнопок меню — по ним же обработчики узнают нажатия
BTN_BOOK = "📅 Записаться"
BTN_MY = "🗓 Мои записи"
BTN_CANCEL = "❌ Отменить"
BTN_PHONE = "📱 Отправить номер"

# Префиксы callback_data. В данных — номера и даты, а не названия:
# у Telegram лимит 64 байта, русский текст быстро его съедает
SERVICE = "svc:"
MASTER = "mst:"
ANY_MASTER = "mst:any"
DAY = "day:"
TIME = "tm:"
BACK = "back:"        # back:services | back:masters | back:days | back:times
CONFIRM = "confirm"
EDIT_CONTACTS = "contacts:me"      # поменять свои сохранённые имя и телефон
GUEST = "contacts:guest"           # записать другого человека — только для этой записи
ABORT = "abort"


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY)]],
        resize_keyboard=True,
    )


cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
                                resize_keyboard=True)

phone_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_PHONE, request_contact=True)],
              [KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _rows(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def services_kb(services: tuple[Service, ...]) -> InlineKeyboardMarkup:
    rows = [[_button(service_button(s), f"{SERVICE}{i}")] for i, s in enumerate(services)]
    rows.append([_button("✖️ Отмена", ABORT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def masters_kb(masters: tuple[Master, ...], all_masters: tuple[Master, ...]) -> InlineKeyboardMarkup:
    """masters — кто делает услугу; номер берём из общего списка, он не меняется."""
    buttons = [_button(m.name, f"{MASTER}{all_masters.index(m)}") for m in masters]
    rows = _rows(buttons, 2)
    if len(masters) > 1:
        rows.insert(0, [_button("🎲 Любой свободный", ANY_MASTER)])
    rows.append([_button("⬅️ Назад", f"{BACK}services")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def days_kb(days: list[date], today: date, back: str) -> InlineKeyboardMarkup:
    buttons = [_button(day_button(d, today), f"{DAY}{d:%Y%m%d}") for d in days]
    rows = _rows(buttons, 3)
    rows.append([_button("⬅️ Назад", f"{BACK}{back}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times_kb(times: list[datetime]) -> InlineKeyboardMarkup:
    buttons = [_button(f"{t:%H:%M}", f"{TIME}{t:%H%M}") for t in times]
    rows = _rows(buttons, 4)
    rows.append([_button("⬅️ Другой день", f"{BACK}days")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("✅ Подтвердить запись", CONFIRM)],
        [_button("✏️ Изменить мои контакты", EDIT_CONTACTS)],
        [_button("👥 Записать другого человека", GUEST)],
        [_button("⬅️ Другое время", f"{BACK}times"), _button("✖️ Отмена", ABORT)],
    ])
