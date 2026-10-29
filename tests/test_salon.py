"""Разбор salon.toml и понятные ошибки для заказчика."""
import tomllib
from datetime import time, timedelta
from pathlib import Path

import pytest

from bot.salon import SalonConfigError, load_salon, parse_salon

ROOT = Path(__file__).resolve().parent.parent


def config(**changes):
    data = {
        "salon": {"name": "Тест"},
        "services": [{"name": "Стрижка", "minutes": 60, "price": 1000}],
        "masters": [{"name": "Анна", "services": ["Стрижка"], "days": ["пн", "сб"],
                     "hours": "10:00-19:00", "breaks": ["14:00-15:00"]}],
    }
    for key, value in changes.items():
        if key in ("services", "masters"):
            data[key] = value
        else:
            data["salon"][key] = value
    return data


def master(**changes):
    raw = {"name": "Анна", "services": ["Стрижка"], "days": ["пн"], "hours": "10:00-19:00"}
    raw.update(changes)
    return [raw]


def test_example_file_is_valid():
    """salon.toml из репозитория должен всегда загружаться."""
    salon = load_salon(ROOT / "salon.toml")
    assert salon.services and salon.masters
    for m in salon.masters:
        assert all(salon.service(s) for s in m.services)


def test_parse_values_and_defaults():
    salon = parse_salon(config())
    anna = salon.master("Анна")
    assert anna.weekdays == frozenset({0, 5})
    assert (anna.start, anna.end) == (time(10), time(19))
    assert anna.breaks == ((time(14), time(15)),)
    assert salon.slot_step == 30 and salon.days_ahead == 14
    assert salon.min_before == timedelta(hours=1)
    assert salon.cancel_before == timedelta(hours=3)
    assert salon.reminders == (24, 2)


def test_reminders_sorted_and_unique():
    assert parse_salon(config(reminders=[2, 24, 2])).reminders == (24, 2)


def test_masters_for_service():
    data = config(
        services=[{"name": "Стрижка", "minutes": 60}, {"name": "Борода", "minutes": 30}],
        masters=[{"name": "Анна", "services": ["Стрижка"], "days": ["пн"], "hours": "10:00-19:00"},
                 {"name": "Борис", "services": ["Стрижка", "Борода"], "days": ["пн"],
                  "hours": "10:00-19:00"}])
    salon = parse_salon(data)
    assert [m.name for m in salon.masters_for("Борода")] == ["Борис"]
    assert [m.name for m in salon.masters_for("Стрижка")] == ["Анна", "Борис"]


@pytest.mark.parametrize("masters, message", [
    (master(services=["Маникюр"]), "нет таких услуг: Маникюр"),
    (master(days=["пнд"]), "рабочие дни"),
    (master(hours="19:00-10:00"), "должно быть раньше"),
    (master(hours="10-19"), "ЧЧ:ММ"),
    (master(breaks=["09:00-10:30"]), "выходит за рабочее время"),
    (master(services=[]), "не указаны services"),
    ([], "Нет ни одного мастера"),
    (master() + master(), "указан(а) дважды"),
])
def test_master_errors(masters, message):
    with pytest.raises(SalonConfigError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_salon(config(masters=masters))


@pytest.mark.parametrize("services, message", [
    ([], "Нет ни одной услуги"),
    ([{"name": "Стрижка", "minutes": 0}], "minutes должно быть"),
    ([{"name": "Стрижка", "minutes": 60, "price": -5}], "price должно быть"),
    ([{"minutes": 60}], "не указано name"),
])
def test_service_errors(services, message):
    with pytest.raises(SalonConfigError, match=message):
        parse_salon(config(services=services))


def test_bad_salon_numbers():
    with pytest.raises(SalonConfigError, match="slot_step"):
        parse_salon(config(slot_step=0))
    with pytest.raises(SalonConfigError, match="cancel_hours_before"):
        parse_salon(config(cancel_hours_before=-1))
    with pytest.raises(SalonConfigError, match="reminders"):
        parse_salon(config(reminders="24"))


def test_missing_and_broken_file(tmp_path):
    with pytest.raises(SalonConfigError, match="Не найден файл"):
        load_salon(tmp_path / "nope.toml")
    broken = tmp_path / "salon.toml"
    broken.write_text("[salon\nname = 1", encoding="utf-8")
    with pytest.raises(SalonConfigError, match="Ошибка в"):
        load_salon(broken)


def test_toml_example_parses_with_tomllib():
    with (ROOT / "salon.toml").open("rb") as f:
        assert "services" in tomllib.load(f)


def test_cancel_reasons():
    assert parse_salon(config()).cancel_reasons == (
        "Мастер заболел", "Технические причины", "Изменился график мастера")
    assert parse_salon(config(cancel_reasons=[" Ремонт "])).cancel_reasons == ("Ремонт",)
    with pytest.raises(SalonConfigError, match="cancel_reasons"):
        parse_salon(config(cancel_reasons=["", "Ок"]))
