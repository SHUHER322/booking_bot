"""Обработчики: меню и запись клиента.

Запись идёт в одном сообщении: на каждом шаге бот меняет его текст и кнопки
(услуга → мастер → день → время → подтверждение). Так чат не засоряется,
а кнопка «Назад» просто показывает предыдущий шаг.
"""
import html
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .availability import free_days, free_times
from .config import Config
from .db import Client, Database
from .keyboards import (ABORT, ANY_MASTER, BACK, BTN_BOOK, BTN_CANCEL, BTN_MY, CONFIRM,
                        DAY, EDIT_CONTACTS, GUEST, MASTER, SERVICE, TIME, cancel_kb, confirm_kb,
                        days_kb, main_kb, masters_kb, phone_kb, services_kb, times_kb)
from .notify import send_to_admins
from .salon import Service
from .states import BookingForm
from .texts import admin_card, booking_card, is_valid_phone, long_date, summary

router = Router()
log = logging.getLogger(__name__)

STALE = "Эта запись уже закрыта. Начните заново: «📅 Записаться»."


# --- что выбрано: всё лежит в данных FSM ---

def chosen_service(data: dict, config: Config) -> Service | None:
    index = data.get("service")
    services = config.salon.services
    # Номер мог устареть, если salon.toml поменяли и перезапустили бота
    return services[index] if isinstance(index, int) and 0 <= index < len(services) else None


def chosen_moment(data: dict) -> datetime | None:
    if not data.get("day") or not data.get("time"):
        return None
    return datetime.strptime(f"{data['day']} {data['time']}", "%Y-%m-%d %H:%M")


async def contact_for(data: dict, user, db: Database) -> Client | None:
    """На кого запись: другой человек (только для этой записи) или сам клиент из базы."""
    if data.get("guest") and data.get("guest_name"):
        # username оставляем того, кто записывает: с ним админ и свяжется в Telegram
        return Client(user.id, data["guest_name"], data["guest_phone"], user.username)
    return await db.get_client(user.id)


def days_back(service: Service, config: Config) -> str:
    """Куда ведёт «Назад» со шага дней: к мастерам, если было из кого выбирать."""
    return "masters" if len(config.salon.masters_for(service.name)) > 1 else "services"


# --- шаги: каждый возвращает текст и кнопки ---

Step = tuple[str, InlineKeyboardMarkup]


def step_services(config: Config) -> Step:
    return "Выберите услугу:", services_kb(config.salon.services)


def step_masters(service: Service, config: Config) -> Step:
    salon = config.salon
    text = summary(service, None).split("\n")[0] + "\n\nВыберите мастера:"
    return text, masters_kb(salon.masters_for(service.name), salon.masters)


async def step_days(data: dict, db: Database, config: Config, note: str = "") -> Step:
    service = chosen_service(data, config)
    now = config.now()
    days = await free_days(db, config.salon, service, data.get("master"), now)
    head = (note + "\n\n" if note else "") + summary(service, data.get("master"))
    if not days:
        text = head + f"\n\nНа ближайшие {config.salon.days_ahead} дн. свободного времени нет 😔"
        if data.get("master"):
            text += "\nПопробуйте другого мастера."
    else:
        text = head + "\n\nВыберите день:"
    return text, days_kb(days, now.date(), days_back(service, config))


async def step_times(data: dict, db: Database, config: Config) -> Step | None:
    """None — если в этот день свободного времени уже не осталось."""
    service = chosen_service(data, config)
    day = date.fromisoformat(data["day"])
    times = await free_times(db, config.salon, service, data.get("master"), day, config.now())
    if not times:
        return None
    text = (summary(service, data.get("master")) +
            f"\n🗓 {long_date(day)}\n\nВыберите время:")
    return text, times_kb(list(times))


def step_confirm(data: dict, client: Client, config: Config) -> Step:
    service = chosen_service(data, config)
    salon = config.salon
    text = (summary(service, data.get("master"), chosen_moment(data)) +
            f"\n📞 {html.escape(client.name)}, {html.escape(client.phone)}")
    if salon.address:
        text += f"\n📍 {html.escape(salon.address)}"
    return "Проверьте запись:\n\n" + text, confirm_kb()


async def show(callback: CallbackQuery, step: Step) -> None:
    text, kb = step
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as error:
        # Двойное нажатие: текст и кнопки не изменились — Telegram ругается, это не ошибка
        if "message is not modified" not in str(error):
            raise
    await callback.answer()


async def restart(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    """Выбор устарел (поменяли salon.toml) — начинаем с услуги."""
    await state.update_data(service=None, master=None, day=None, time=None)
    await show(callback, step_services(config))


# --- меню. Эти обработчики первыми: нажатие кнопки меню посреди записи
# не должно приниматься за имя или телефон ---

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, config: Config):
    await state.clear()
    salon = config.salon
    text = f"Здравствуйте! Это бот записи в <b>{html.escape(salon.name)}</b>."
    if salon.address:
        text += f"\n📍 {html.escape(salon.address)}"
    text += f"\n\nНажмите «{BTN_BOOK}», чтобы выбрать услугу, мастера и удобное время."
    await message.answer(text, reply_markup=main_kb())


@router.message(or_f(Command("cancel"), F.text == BTN_CANCEL))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Запись отменена.", reply_markup=main_kb())


@router.message(or_f(Command("book"), F.text == BTN_BOOK))
async def book(message: Message, state: FSMContext, config: Config):
    await state.clear()
    await state.set_state(BookingForm.choosing)
    text, kb = step_services(config)
    await message.answer(text, reply_markup=kb)


@router.message(or_f(Command("my"), F.text == BTN_MY))
async def my_bookings(message: Message, db: Database, config: Config):
    # Полноценный список с отменой — на следующем шаге
    bookings = await db.user_bookings(message.from_user.id, config.now())
    if not bookings:
        await message.answer("У вас нет предстоящих записей.", reply_markup=main_kb())
        return
    await message.answer("\n\n".join(booking_card(b) for b in bookings), reply_markup=main_kb())


# --- шаги записи (кнопки под сообщением) ---

@router.callback_query(BookingForm.choosing, F.data.startswith(SERVICE))
async def pick_service(callback: CallbackQuery, state: FSMContext, db: Database, config: Config):
    index = int(callback.data.removeprefix(SERVICE))
    data = await state.update_data(service=index, master=None, day=None, time=None)
    service = chosen_service(data, config)
    if not service:
        await restart(callback, state, config)
        return
    masters = config.salon.masters_for(service.name)
    if len(masters) == 1:
        # Выбирать не из кого — сразу к дням, мастера подставляем сами
        data = await state.update_data(master=masters[0].name)
        await show(callback, await step_days(data, db, config))
    else:
        await show(callback, step_masters(service, config))


@router.callback_query(BookingForm.choosing, F.data.startswith(MASTER))
async def pick_master(callback: CallbackQuery, state: FSMContext, db: Database, config: Config):
    data = await state.get_data()
    service = chosen_service(data, config)
    if callback.data == ANY_MASTER:
        master = None
    else:
        index = int(callback.data.removeprefix(MASTER))
        masters = config.salon.masters
        master = masters[index].name if 0 <= index < len(masters) else ""
    if not service or (master is not None and master not in
                       [m.name for m in config.salon.masters_for(service.name)]):
        await restart(callback, state, config)
        return
    data = await state.update_data(master=master, day=None, time=None)
    await show(callback, await step_days(data, db, config))


@router.callback_query(BookingForm.choosing, F.data.startswith(DAY))
async def pick_day(callback: CallbackQuery, state: FSMContext, db: Database, config: Config):
    day = datetime.strptime(callback.data.removeprefix(DAY), "%Y%m%d").date()
    data = await state.update_data(day=day.isoformat(), time=None)
    today = config.now().date()
    if not chosen_service(data, config) or not 0 <= (day - today).days < config.salon.days_ahead:
        await restart(callback, state, config)
        return
    step = await step_times(data, db, config)
    if step is None:
        # Пока клиент выбирал, последнее время в этот день заняли
        await show(callback, await step_days(data, db, config,
                                             note="В этот день свободного времени уже нет."))
        return
    await show(callback, step)


@router.callback_query(BookingForm.choosing, F.data.startswith(TIME))
async def pick_time(callback: CallbackQuery, state: FSMContext, db: Database, config: Config):
    raw = callback.data.removeprefix(TIME)
    data = await state.update_data(time=f"{raw[:2]}:{raw[2:]}")
    if not chosen_service(data, config) or not data.get("day"):
        await restart(callback, state, config)
        return
    client = await contact_for(data, callback.from_user, db)
    if client:
        await show(callback, step_confirm(data, client, config))
        return
    # Первая запись — спросим имя и телефон, потом их запомним
    await callback.message.edit_text(
        summary(chosen_service(data, config), data.get("master"), chosen_moment(data)))
    await callback.answer()
    await callback.message.answer("Как вас зовут?", reply_markup=cancel_kb)
    await state.set_state(BookingForm.name)


@router.callback_query(BookingForm.choosing, F.data.startswith(BACK))
async def go_back(callback: CallbackQuery, state: FSMContext, db: Database, config: Config):
    target = callback.data.removeprefix(BACK)
    data = await state.get_data()
    service = chosen_service(data, config)
    if target == "services" or not service:
        await show(callback, step_services(config))
    elif target == "masters":
        await show(callback, step_masters(service, config))
    elif target == "days" or not data.get("day"):
        await show(callback, await step_days(data, db, config))
    else:  # times
        step = await step_times(data, db, config)
        await show(callback, step or await step_days(data, db, config))


@router.callback_query(BookingForm.choosing, F.data.in_({EDIT_CONTACTS, GUEST}))
async def other_contacts(callback: CallbackQuery, state: FSMContext, config: Config):
    guest = callback.data == GUEST
    data = await state.update_data(guest=guest)
    await callback.message.edit_text(
        summary(chosen_service(data, config), data.get("master"), chosen_moment(data)))
    await callback.answer()
    question = "Как зовут человека, которого записываете?" if guest else "Как вас зовут?"
    await callback.message.answer(question, reply_markup=cancel_kb)
    await state.set_state(BookingForm.name)


@router.callback_query(BookingForm.choosing, F.data == ABORT)
async def abort(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Запись отменена.")
    await callback.answer()


@router.callback_query(BookingForm.choosing, F.data == CONFIRM)
async def confirm(callback: CallbackQuery, state: FSMContext, bot: Bot,
                  db: Database, config: Config):
    data = await state.get_data()
    service, moment = chosen_service(data, config), chosen_moment(data)
    client = await contact_for(data, callback.from_user, db)
    if not service or not moment or not client:
        await restart(callback, state, config)
        return

    now = config.now()
    # Кто свободен в это время прямо сейчас: выбранный мастер или любой из подходящих
    free = (await free_times(db, config.salon, service, data.get("master"),
                             moment.date(), now)).get(moment, [])
    booking = None
    for master in free:
        # Базу проверяем ещё раз внутри add_booking: между расчётом и сохранением
        # время мог занять другой клиент — тогда пробуем следующего мастера
        booking = await db.add_booking(client, master, service.name, service.price,
                                       moment, moment + timedelta(minutes=service.minutes), now)
        if booking:
            break

    if not booking:
        await callback.answer("Это время только что заняли 😔 Выберите другое.", show_alert=True)
        step = await step_times(data, db, config) or await step_days(data, db, config)
        text, kb = step
        await callback.message.edit_text(text, reply_markup=kb)
        return

    await state.clear()
    text = "✅ <b>Вы записаны!</b>\n\n" + booking_card(booking)
    if config.salon.address:
        text += f"\n📍 {html.escape(config.salon.address)}"
    if config.salon.reminders:
        hours = " и ".join(f"{h} ч" for h in config.salon.reminders)
        text += f"\n\nНапомню за {hours} до визита. Отменить запись — «{BTN_MY}»."
    await callback.message.edit_text(text)
    await callback.answer()
    await send_to_admins(bot, config.admin_chat_ids, admin_card(booking, "🆕 <b>Новая запись</b>"))


@router.callback_query()
async def stale_button(callback: CallbackQuery):
    """Кнопка из старого или уже закрытого сообщения."""
    await callback.answer(STALE, show_alert=True)


# --- имя и телефон (только при первой записи или по кнопке «Другое имя») ---

@router.message(BookingForm.name, F.text)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 50:
        await message.answer("Введите имя от 2 до 50 символов.")
        return
    await state.update_data(name=name)
    await message.answer("Укажите телефон или нажмите кнопку ниже.", reply_markup=phone_kb)
    await state.set_state(BookingForm.phone)


@router.message(BookingForm.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext, db: Database, config: Config):
    await _save_contacts(message, state, db, config, message.contact.phone_number)


@router.message(BookingForm.phone, F.text)
async def get_phone_text(message: Message, state: FSMContext, db: Database, config: Config):
    phone = message.text.strip()
    if not is_valid_phone(phone):
        await message.answer("Не похоже на номер. Пример: +7 913 123-45-67")
        return
    await _save_contacts(message, state, db, config, phone)


async def _save_contacts(message: Message, state: FSMContext, db: Database,
                         config: Config, phone: str):
    data = await state.get_data()
    user = message.from_user
    client = Client(user.id, data["name"], phone, user.username)
    if data.get("guest"):
        # Чужие контакты — только в эту запись, сохранённые контакты клиента не трогаем
        data = await state.update_data(guest_name=client.name, guest_phone=phone)
        reply = f"Записываю на имя {html.escape(client.name)}."
    else:
        await db.save_client(client)
        reply = "Спасибо, запомнил — в следующий раз спрашивать не буду."
    await state.set_state(BookingForm.choosing)
    # Убираем кнопку «Отправить номер», возвращаем меню
    await message.answer(reply, reply_markup=main_kb())
    text, kb = step_confirm(data, client, config)
    await message.answer(text, reply_markup=kb)


@router.message(BookingForm.name)
@router.message(BookingForm.phone)
async def wrong_input(message: Message):
    await message.answer("Пожалуйста, отправьте текстом.")


@router.message(BookingForm.choosing)
async def choosing_text(message: Message):
    await message.answer("Выберите вариант кнопкой под сообщением выше "
                         f"или нажмите «{BTN_CANCEL}».", reply_markup=cancel_kb)


@router.message()
async def fallback(message: Message):
    await message.answer(f"Чтобы записаться, нажмите «{BTN_BOOK}».", reply_markup=main_kb())
