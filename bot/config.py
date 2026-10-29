"""Загрузка настроек: секреты и окружение — из .env, салон — из salon.toml."""
import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .salon import Salon, load_salon

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    # Кому слать уведомления о записях: один или несколько админов (или ID группы)
    admin_chat_ids: tuple[int, ...]
    db_path: str
    # Часовой пояс салона: по нему считаются слоты и напоминания
    timezone: ZoneInfo
    salon: Salon

    def now(self) -> datetime:
        """Текущее время салона без пояса — в таком виде хранится всё время в боте."""
        return datetime.now(self.timezone).replace(tzinfo=None, second=0, microsecond=0)


def _parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise RuntimeError(f"Неизвестный часовой пояс TIMEZONE={name!r}. "
                           "Пример: Asia/Tomsk, Europe/Moscow")


def parse_chat_ids(value: str) -> tuple[int, ...]:
    """'574340592, 6592299831' → (574340592, 6592299831). Повторы убираются."""
    ids: list[int] = []
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        try:
            chat_id = int(part)
        except ValueError:
            raise RuntimeError("ADMIN_CHAT_ID — один или несколько ID через запятую, "
                               f"например 123456789,987654321. Сейчас: {value!r}")
        if chat_id not in ids:
            ids.append(chat_id)
    if not ids:
        raise RuntimeError("ADMIN_CHAT_ID пустой: укажи хотя бы один ID")
    return tuple(ids)


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    admin_ids = os.getenv("ADMIN_CHAT_ID")
    if not token or not admin_ids:
        raise RuntimeError("Заполни BOT_TOKEN и ADMIN_CHAT_ID в файле .env")
    return Config(
        bot_token=token,
        admin_chat_ids=parse_chat_ids(admin_ids),
        db_path=os.getenv("DB_PATH", "bookings.db"),
        timezone=_parse_timezone(os.getenv("TIMEZONE", "Asia/Tomsk")),
        salon=load_salon(os.getenv("SALON_CONFIG", "salon.toml")),
    )
