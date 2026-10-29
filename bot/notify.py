"""Отправка сообщений всем админам."""
import asyncio
import logging

log = logging.getLogger(__name__)


async def send_to_admins(bot, chat_ids, text: str) -> int:
    """Отправить текст каждому админу. Если один заблокировал бота или
    недоступен — остальные всё равно получат. Возвращает, скольким дошло."""
    delivered = 0
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, text)
            delivered += 1
        except Exception:
            log.exception("Не удалось отправить админу %s", chat_id)
        await asyncio.sleep(0.05)  # Telegram ограничивает частоту сообщений
    return delivered
