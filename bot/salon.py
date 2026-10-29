"""Настройки салона из salon.toml: услуги, мастера, графики работы."""
import tomllib
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path

DEFAULT_CANCEL_REASONS = ("Мастер заболел", "Технические причины", "Изменился график мастера")
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")  # индекс = date.weekday()


@dataclass(frozen=True)
class Service:
    name: str
    minutes: int
    price: int


@dataclass(frozen=True)
class Master:
    name: str
    services: tuple[str, ...]
    weekdays: frozenset[int]          # 0 — понедельник … 6 — воскресенье
    start: time                       # начало рабочего дня
    end: time                         # конец рабочего дня
    breaks: tuple[tuple[time, time], ...] = ()

    def works_on(self, weekday: int) -> bool:
        return weekday in self.weekdays

    def does(self, service: str) -> bool:
        return service in self.services


@dataclass(frozen=True)
class Salon:
    name: str
    address: str
    slot_step: int                    # шаг сетки времени, минуты
    days_ahead: int                   # на сколько дней вперёд показывать запись
    min_before: timedelta             # запись не раньше чем за … до начала
    cancel_before: timedelta          # самостоятельная отмена не позже чем за …
    reminders: tuple[int, ...]        # за сколько часов напоминать, по убыванию
    services: tuple[Service, ...]
    masters: tuple[Master, ...]
    phone: str = ""                   # телефон салона — подсказываем, если отменить уже поздно
    cancel_reasons: tuple[str, ...] = DEFAULT_CANCEL_REASONS  # кнопки причин отмены для админа

    def service(self, name: str) -> Service | None:
        return next((s for s in self.services if s.name == name), None)

    def master(self, name: str) -> Master | None:
        return next((m for m in self.masters if m.name == name), None)

    def masters_for(self, service: str) -> tuple[Master, ...]:
        """Мастера, которые делают эту услугу."""
        return tuple(m for m in self.masters if m.does(service))


class SalonConfigError(RuntimeError):
    """Ошибка в salon.toml — текст понятен заказчику, без трейсбека."""


def _time(value: str, where: str) -> time:
    try:
        hours, minutes = value.strip().split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        raise SalonConfigError(f"{where}: время должно быть в формате ЧЧ:ММ, сейчас {value!r}")


def _interval(value: str, where: str) -> tuple[time, time]:
    """'10:00-19:00' → (10:00, 19:00)"""
    parts = str(value).split("-")
    if len(parts) != 2:
        raise SalonConfigError(f"{where}: нужен интервал вида 10:00-19:00, сейчас {value!r}")
    start, end = _time(parts[0], where), _time(parts[1], where)
    if start >= end:
        raise SalonConfigError(f"{where}: начало {start:%H:%M} должно быть раньше конца {end:%H:%M}")
    return start, end


def _positive_int(table: dict, key: str, where: str, default: int | None = None) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SalonConfigError(f"{where}: {key} должно быть целым числом больше нуля, сейчас {value!r}")
    return value


def _hours(table: dict, key: str, default: float) -> timedelta:
    value = table.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise SalonConfigError(f"[salon]: {key} должно быть числом часов ≥ 0, сейчас {value!r}")
    return timedelta(hours=value)


def _parse_service(raw: dict, i: int) -> Service:
    where = f"Услуга №{i}"
    name = str(raw.get("name", "")).strip()
    if not name:
        raise SalonConfigError(f"{where}: не указано name")
    where = f"Услуга «{name}»"
    price = raw.get("price", 0)
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise SalonConfigError(f"{where}: price должно быть целым числом ≥ 0, сейчас {price!r}")
    return Service(name, _positive_int(raw, "minutes", where), price)


def _parse_master(raw: dict, i: int, service_names: set[str]) -> Master:
    where = f"Мастер №{i}"
    name = str(raw.get("name", "")).strip()
    if not name:
        raise SalonConfigError(f"{where}: не указано name")
    where = f"Мастер «{name}»"

    services = tuple(str(s).strip() for s in raw.get("services", []))
    if not services:
        raise SalonConfigError(f"{where}: не указаны services — какие услуги делает мастер")
    unknown = [s for s in services if s not in service_names]
    if unknown:
        raise SalonConfigError(f"{where}: нет таких услуг: {', '.join(unknown)}. "
                               "Названия должны совпадать с [[services]]")

    days = [str(d).strip().lower() for d in raw.get("days", [])]
    bad_days = [d for d in days if d not in WEEKDAYS]
    if not days or bad_days:
        raise SalonConfigError(f"{where}: days — рабочие дни из списка {' '.join(WEEKDAYS)}, "
                               f"сейчас {raw.get('days')!r}")

    start, end = _interval(raw.get("hours", ""), f"{where}, hours")
    breaks = tuple(sorted(_interval(b, f"{where}, breaks") for b in raw.get("breaks", [])))
    for b_start, b_end in breaks:
        if b_start < start or b_end > end:
            raise SalonConfigError(f"{where}: перерыв {b_start:%H:%M}-{b_end:%H:%M} "
                                   "выходит за рабочее время")
    return Master(name, services, frozenset(WEEKDAYS.index(d) for d in days),
                  start, end, breaks)


def _unique(names: list[str], what: str) -> None:
    seen = set()
    for name in names:
        if name in seen:
            raise SalonConfigError(f"{what} «{name}» указан(а) дважды")
        seen.add(name)


def parse_salon(data: dict) -> Salon:
    """Разбор уже прочитанного TOML. Отдельно от чтения файла — так проще тестировать."""
    head = data.get("salon", {})
    services = tuple(_parse_service(s, i) for i, s in enumerate(data.get("services", []), 1))
    if not services:
        raise SalonConfigError("Нет ни одной услуги: добавьте блоки [[services]]")
    _unique([s.name for s in services], "Услуга")

    names = {s.name for s in services}
    masters = tuple(_parse_master(m, i, names) for i, m in enumerate(data.get("masters", []), 1))
    if not masters:
        raise SalonConfigError("Нет ни одного мастера: добавьте блоки [[masters]]")
    _unique([m.name for m in masters], "Мастер")

    reminders = head.get("reminders", [24, 2])
    if not isinstance(reminders, list) or not all(
            isinstance(h, int) and not isinstance(h, bool) and h > 0 for h in reminders):
        raise SalonConfigError(f"reminders — список часов, например [24, 2], сейчас {reminders!r}")

    reasons = head.get("cancel_reasons", list(DEFAULT_CANCEL_REASONS))
    if not isinstance(reasons, list) or not all(isinstance(r, str) and r.strip() for r in reasons):
        raise SalonConfigError("cancel_reasons — список причин в кавычках, "
                               f'например ["Мастер заболел"], сейчас {reasons!r}')

    return Salon(
        cancel_reasons=tuple(r.strip() for r in reasons),
        name=str(head.get("name", "Салон")).strip(),
        address=str(head.get("address", "")).strip(),
        phone=str(head.get("phone", "")).strip(),
        slot_step=_positive_int(head, "slot_step", "[salon]", 30),
        days_ahead=_positive_int(head, "days_ahead", "[salon]", 14),
        min_before=_hours(head, "min_hours_before", 1),
        cancel_before=_hours(head, "cancel_hours_before", 3),
        reminders=tuple(sorted(set(reminders), reverse=True)),
        services=services,
        masters=masters,
    )


def load_salon(path: str | Path) -> Salon:
    path = Path(path)
    if not path.exists():
        raise SalonConfigError(f"Не найден файл {path}. Скопируйте salon.toml из репозитория")
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SalonConfigError(f"Ошибка в {path}: {e}")
    return parse_salon(data)
