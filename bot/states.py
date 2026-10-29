"""Шаги записи (машина состояний)."""
from aiogram.fsm.state import State, StatesGroup


class BookingForm(StatesGroup):
    choosing = State()   # услуга → мастер → день → время → подтверждение (кнопки под сообщением)
    name = State()       # имя — только при первой записи или по кнопке «Другое имя»
    phone = State()
