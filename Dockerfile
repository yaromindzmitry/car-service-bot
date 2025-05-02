FROM python:3.11-slim

# Устанавливаем базовые пакеты
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Переменная среды
ENV PYTHONUNBUFFERED=1

# Работаем в папке приложения
WORKDIR /app

# Копируем зависимости и ставим их
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Стартуем бота
CMD ["python", "bot.py"]
