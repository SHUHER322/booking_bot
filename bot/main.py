"""Точка входа: python -m bot.main"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from .config import load_config
from .db import Database
from .handlers import router

log = logging.getLogger(__name__)


async def setup_commands(bot: Bot) -> None:
    """Список команд для кнопки «Меню»."""
    commands = [
        BotCommand(command="book", description="Записаться"),
        BotCommand(command="my", description="Мои записи"),
        BotCommand(command="cancel", description="Отменить текущую запись"),
    ]
    try:  # не критично: без меню бот работает, кнопки остаются
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception:
        log.exception("Не удалось установить список команд")


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    salon = config.salon
    log.info("Салон «%s»: услуг %d, мастеров %d", salon.name,
             len(salon.services), len(salon.masters))

    db = Database(config.db_path)
    await db.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # db и config передаются в обработчики как аргументы
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config)
    dp.include_router(router)
    await setup_commands(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен")
    except RuntimeError as error:
        # Ошибки настроек (.env, salon.toml) — коротким понятным текстом, без трейсбека
        log.error("%s", error)
        raise SystemExit(1)
