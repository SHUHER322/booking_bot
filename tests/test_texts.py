"""Форматирование: даты по-русски, цены, длительность, телефон."""
from datetime import date, datetime

import pytest

from bot.texts import day_button, duration, is_valid_phone, long_date, rub, when

TODAY = date(2026, 11, 2)  # понедельник


def test_rub_uses_non_breaking_space():
    assert rub(1700) == "1 700 ₽"
    assert rub(600) == "600 ₽"


@pytest.mark.parametrize("minutes, text", [(30, "30 мин"), (60, "1 ч"), (90, "1 ч 30 мин")])
def test_duration(minutes, text):
    assert duration(minutes) == text


def test_day_button():
    assert day_button(TODAY, TODAY) == "Сегодня 02.11"
    assert day_button(date(2026, 11, 3), TODAY) == "Завтра 03.11"
    assert day_button(date(2026, 11, 6), TODAY) == "Пт 06.11"


def test_long_date_and_when():
    assert long_date(date(2026, 11, 6)) == "пятница, 6 ноября"
    assert when(datetime(2026, 3, 1, 9, 5)) == "воскресенье, 1 марта, 09:05"


@pytest.mark.parametrize("phone, ok", [
    ("+7 913 123-45-67", True), ("89131234567", True), ("8 (913) 123 45 67", True),
    ("12345", False), ("----------", False), ("+7 913 abc", False),
])
def test_phone(phone, ok):
    assert is_valid_phone(phone) is ok
