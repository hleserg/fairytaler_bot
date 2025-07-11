# Storyteller Bot

Генерирует сказки на ночь по параметрам пользователя через Telegram. Поддерживает генерацию аудиосказок с помощью Yandex SpeechKit.

## Возможности
- Интерактивный выбор параметров сказки (герой, место, настроение, возраст, длина)
- Генерация текста сказки через NeuroAPI (Gemini/ChatGPT)
- Команда `/audio` — генерация аудиофайла сказки (OGG)
- Для длинных сказок (выбран вариант "длинная") аудио разбивается на две части
- Команда `/test` — тестовое аудио для отладки TTS
- Поддержка Docker и Docker Compose

## Быстрый старт (локально)

1. Установите зависимости:
   ```sh
   pip install -r requirements.txt
   ```
2. Укажите токены в `.env` или переменных окружения:
   - `TELEGRAM_BOT_TOKEN` — токен Telegram-бота
   - `NEUROAPI_API_KEY` — ключ NeuroAPI
   - `YANDEX_FOLDER_ID` — folder_id для Yandex SpeechKit
   - `YANDEX_IAM_TOKEN` — IAM-токен для Yandex SpeechKit
3. Запустите:
   ```sh
   python bot.py
   ```

## Запуск через Docker Compose

1. Заполните `.env` (см. пример выше).
2. Соберите и запустите:
   ```sh
   docker-compose up --build
   ```

## Переменные окружения
- `TELEGRAM_BOT_TOKEN` — токен Telegram-бота
- `NEUROAPI_API_KEY` — ключ NeuroAPI
- `YANDEX_FOLDER_ID` — folder_id для Yandex SpeechKit
- `YANDEX_IAM_TOKEN` — IAM-токен для Yandex SpeechKit

## Основные команды бота
- `/start` — начать создание новой сказки
- `/new` — начать заново
- `/audio` — получить аудиофайл сказки (OGG, для длинных — две части)
- `/test` — тестовое аудио для проверки TTS
- `/help` — справка

## Файлы
- `bot.py` — основной код бота
- `requirements.txt` — зависимости
- `Dockerfile` — сборка контейнера
- `docker-compose.yml` — запуск через Docker Compose
- `.env` — переменные окружения

