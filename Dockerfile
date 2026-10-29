# Рецепт «коробки» с ботом
FROM python:3.14-slim

# Не создавать .pyc-файлы и сразу выводить логи (без буферизации)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала только зависимости: Docker запомнит этот слой, и при изменении
# кода библиотеки не будут переустанавливаться заново
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY salon.toml .

CMD ["python", "-m", "bot.main"]
