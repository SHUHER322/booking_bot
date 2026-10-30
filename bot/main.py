"""Точка входа: python -m bot.main"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from .config import load_config
from .db import Database
from .reminders import reminders_loop
from . import admin, handlers, my_bookings

log = logging.getLogger(__name__)


async def setup_commands(bot: Bot, config) -> None:
    """Список команд для кнопки «Меню». Админы видят ещё и расписание."""
    commands = [
        BotCommand(command="book", description="Записаться"),
        BotCommand(command="my", description="Мои записи"),
        BotCommand(command="cancel", description="Отменить текущую запись"),
    ]
    try:  # не критично: без меню бот работает, кнопки остаются
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception:
        log.exception("Не удалось установить список команд")
    admin_commands = [BotCommand(command="today", description="Расписание на сегодня"),
                      BotCommand(command="tomorrow", description="Расписание на завтра")]
    for chat_id in config.admin_chat_ids:
        try:
            await bot.set_my_commands(admin_commands + commands,
                                      scope=BotCommandScopeChat(chat_id=chat_id))
        except Exception:
            # Например, админ ещё ни разу не писал боту — Telegram не знает этот чат
            log.exception("Не удалось установить команды для админа %s", chat_id)


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
    # Админ и «Мои записи» — раньше общего роутера: в его конце стоит
    # «ловушка» для старых кнопок, она перехватила бы их нажатия
    dp.include_router(admin.router)
    dp.include_router(my_bookings.router)
    dp.include_router(handlers.router)
    await setup_commands(bot, config)

    # Напоминания работают параллельно с приёмом сообщений
    reminders_task = asyncio.create_task(reminders_loop(bot, db, config))
    try:
        await dp.start_polling(bot)
    finally:
        reminders_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен")
    except RuntimeError as error:
        # Ошибки настроек (.env, salon.toml) — коротким понятным текстом, без трейсбека
        log.error("%s", error)
        raise SystemExit(1)
