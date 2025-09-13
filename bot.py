import os
import logging
import tempfile
import requests
import aiohttp
import asyncio
import json
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
)
from telegram.constants import ChatAction
import subprocess

# Загружаем переменные из .env файла
load_dotenv()

# --- Конфиг ---
NEUROAPI_API_KEY = os.getenv('NEUROAPI_API_KEY')
NEUROAPI_URL = 'https://neuroapi.host/v1/chat/completions'
MODEL = 'gemini-2.5-pro'

folder_id = os.getenv('YC_FOLDER_ID') or os.getenv('YANDEX_FOLDER_ID')
# iam_token теперь будет обновляться автоматически
iam_token = None

# Yandex Art API
YANDEX_ART_URL = 'https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync'
YANDEX_OPERATIONS_URL = 'https://llm.api.cloud.yandex.net/operations'

# --- Получение IAM токена через yc CLI ---
def fetch_iam_token():
    try:
        result = subprocess.run(['yc', 'iam', 'create-token'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                logging.info('IAM токен успешно получен через yc CLI')
                return token
            else:
                logging.error('Пустой IAM токен от yc CLI')
        else:
            logging.error(f'Ошибка yc CLI: {result.stderr}')
    except Exception as e:
        logging.error(f'Ошибка получения IAM токена: {e}')
    return None

# --- Планировщик для обновления токена ---
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import pytz

def schedule_iam_token_update():
    global iam_token
    def update_token():
        global iam_token
        token = fetch_iam_token()
        if token:
            iam_token = token
    update_token()  # Получить токен при запуске
    scheduler = BackgroundScheduler(timezone=pytz.UTC)
    scheduler.add_job(update_token, 'interval', hours=24)
    scheduler.start()

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Варианты выбора ---
HEROES = [
    ("🐰 Зайчик", "зайчик"),
    ("👧 Девочка", "девочка"),
    ("🐉 Дракончик", "дракончик"),
    ("🤖 Робот", "робот"),
    ("🐻 Медвежонок", "медвежонок"),
    ("✏️ Свой вариант", "custom")
]
PLACES = [
    ("🌲 Заколдованный лес", "заколдованный лес"),
    ("🏰 Волшебный замок", "волшебный замок"),
    ("🚀 Мир будущего", "мир будущего"),
    ("🏝️ Остров сокровищ", "остров сокровищ"),
    ("✏️ Свой вариант", "custom")
]
MOODS = [
    ("😌 Спокойное", "спокойное"),
    ("✨ Волшебное", "волшебное"),
    ("😄 Весёлое", "весёлое"),
    ("📚 Поучительное", "поучительное"),
    ("🪐 Фантастическое", "фантастическое"),
    ("👻 Страшное", "страшное")
]
AGES = [
    ("👶 Малыш", "малыш"),
    ("🧒 Ребёнок", "ребёнок"),
    ("🧑 Подросток", "подросток"),
    ("🧔 Взрослый", "взрослый")
]
LENGTHS = [
    ("📏 Короткая", "short"),
    ("📖 Средняя", "medium"),
    ("🧾 Длинная", "long")
]


# --- Состояния пользователя ---
USER_STATE = {}

# --- Последние сказки пользователей ---
USER_STORY = {}

# --- Хелперы ---
def build_keyboard(options):
    keyboard = [[InlineKeyboardButton(text, callback_data=val)] for text, val in options]
    return InlineKeyboardMarkup(keyboard)

def reset_user(user_id):
    USER_STATE[user_id] = {
        'step': 'hero',
        'hero': None,
        'place': None,
        'mood': None,
        'age': None,
        'length': None
    }

def get_prompt(state):
    length_map = {
        'short': 250,
        'medium': 550,
        'long': 1000
    }
    length_label = {
        'short': 'короткая',
        'medium': 'средняя',
        'long': 'длинная'
    }
    words = length_map.get(state.get('length'), 500)
    label = length_label.get(state.get('length'), 'короткая')
    return (
        f"Придумай {label} сказку на ночь для возраста: {state['age']}. "
        f"Главный герой: {state['hero']}. Место действия: {state['place']}. "
        f"Настроение: {state['mood']}. Сделай сказку интересной, доброй и подходящей для сна. "
        f"Длина сказки должна быть не менее {words} слов. "
        f"Не используй символы разметки или HTML, только текст сказки."
    )

def generate_story(prompt):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NEUROAPI_API_KEY}"
    }
    data = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    resp = requests.post(NEUROAPI_URL, headers=headers, json=data, timeout=300)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']

# --- Генерация изображений ---
def create_image_prompt(state, text_part=None):
    """Создать промпт для генерации изображения"""
    if text_part:
        # Промпт на основе последних двух предложений блока
        # Разделяем текст на предложения
        sentences = re.split(r'[.!?]+', text_part)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Берем последние два предложения
        if len(sentences) >= 2:
            last_sentences = '. '.join(sentences[-2:])
        elif len(sentences) == 1:
            last_sentences = sentences[0]
        else:
            # Если предложений нет, используем первые 200 символов как fallback
            last_sentences = text_part[:200]
        
        return f"иллюстрация к детской сказке: {last_sentences} в стиле детской книжной иллюстрации, яркие цвета, добрая атмосфера"
    else:
        # Начальный промпт на основе параметров
        mood_map = {
            'спокойное': 'мирная спокойная атмосфера',
            'волшебное': 'магическая волшебная атмосфера с блестками',
            'весёлое': 'яркая радостная атмосфера',
            'поучительное': 'мудрая добрая атмосфера',
            'фантастическое': 'фантастическая космическая атмосфера',
            'страшное': 'немного таинственная но не пугающая атмосфера'
        }
        mood_desc = mood_map.get(state['mood'], 'добрая атмосфера')
        return f"детская книжная иллюстрация: {state['hero']} в месте {state['place']}, {mood_desc}, яркие цвета, стиль детской книги"

async def generate_image(prompt_text):
    """Генерация изображения через Yandex Art API с универсальной обработкой данных"""
    logging.info(f"Начинаем генерацию изображения для промпта: {prompt_text}")
    
    try:
        global iam_token
        if not iam_token:
            iam_token = fetch_iam_token()
            if not iam_token:
                raise Exception('Не удалось получить IAM токен для генерации изображения')
        
        headers = {
            'Authorization': f'Bearer {iam_token}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "modelUri": f"art://{folder_id}/yandex-art/latest",
            "generationOptions": {
                "seed": str(hash(prompt_text) % 10000),
                "aspectRatio": {
                    "widthRatio": "2",
                    "heightRatio": "1"
                }
            },
            "messages": [
                {
                    "text": prompt_text
                }
            ]
        }
        
        logging.info(f"Отправляем запрос на генерацию изображения: {prompt_text[:100]}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(YANDEX_ART_URL, headers=headers, json=data) as resp:
                logging.info(f"Статус ответа API: {resp.status}")
                logging.info(f"Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
                
                if resp.status != 200:
                    error_text = await resp.text()
                    logging.error(f"Art API error (status {resp.status}): {error_text}")
                    raise Exception(f"Art API error (status {resp.status}): {error_text}")
                
                # Проверяем тип контента
                content_type = resp.headers.get('Content-Type', '').lower()
                if 'image' in content_type or 'application/octet-stream' in content_type:
                    # API вернул изображение напрямую (синхронный режим)
                    logging.info("API вернул изображение напрямую (синхронный режим)")
                    image_data = await resp.read()
                    logging.info(f"Размер полученного изображения: {len(image_data)} байт")
                    
                    # Используем универсальную функцию сохранения
                    return await save_image_data(image_data, "синхронное изображение")
                    
                else:
                    # API вернул JSON с operation_id (асинхронный режим)
                    response_text = await resp.text()
                    logging.info(f"Ответ API (JSON): {response_text}")
                    
                    result = await resp.json()
                    operation_id = result['id']
                    logging.info(f"Получен operation_id: {operation_id}")
                    
                    # Ждем завершения генерации
                    check_url = f"{YANDEX_OPERATIONS_URL}/{operation_id}"
                    logging.info(f"Проверяем статус операции по URL: {check_url}")
                    
                    for attempt in range(30):  # максимум 30 попыток (5 минут)
                        await asyncio.sleep(10)
                        logging.info(f"Попытка {attempt + 1}/30 проверки статуса...")
                        
                        async with session.get(check_url, headers=headers) as check_resp:
                            if check_resp.status != 200:
                                error_text = await check_resp.text()
                                logging.error(f"Ошибка проверки статуса (status {check_resp.status}): {error_text}")
                                continue
                                
                            check_result = await check_resp.json()
                            logging.info(f"Статус операции: {json.dumps(check_result, ensure_ascii=False)}")
                            
                            if check_result.get('done'):
                                logging.info("Операция завершена! Анализируем результат...")
                                
                                if 'error' in check_result:
                                    logging.error(f"Ошибка в результате: {check_result['error']}")
                                    raise Exception(f"Art generation error: {check_result['error']}")
                                
                                if 'response' in check_result:
                                    response_data = check_result['response']
                                    logging.info(f"Найден блок response с ключами: {list(response_data.keys())}")
                                    
                                    if 'image' in response_data:
                                        image_data = response_data['image']
                                        logging.info(f"Найдено поле image! Тип: {type(image_data)}")
                                        
                                        # Используем универсальную функцию сохранения
                                        return await save_image_data(image_data, "асинхронное изображение")
                                    else:
                                        logging.error(f"Нет поля image в response! Ключи: {list(response_data.keys())}")
                                        raise Exception(f"Неожиданный формат ответа: {check_result}")
                                else:
                                    logging.error("Нет блока response в результате!")
                                    raise Exception(f"Неожиданный формат ответа: {check_result}")
                    
                    raise Exception("Timeout waiting for image generation")
    
    except Exception as e:
        logging.error(f"Ошибка генерации изображения: {e}")
        logging.error(f"Тип ошибки: {type(e).__name__}")
        import traceback
        logging.error(f"Трассировка: {traceback.format_exc()}")
        return None

def split_story_into_sentences(story):
    """Разделить сказку на части по ~10 предложений"""
    # Разделяем по предложениям
    sentences = re.split(r'[.!?]+', story)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    parts = []
    current_part = []
    
    for sentence in sentences:
        current_part.append(sentence)
        if len(current_part) >= 10:
            parts.append('. '.join(current_part) + '.')
            current_part = []
    
    # Добавить оставшиеся предложения
    if current_part:
        parts.append('. '.join(current_part) + '.')
    
    return parts

async def save_image_data(image_data, description="image"):
    """Универсальная функция для сохранения данных изображения в временный файл"""
    logging.info(f"Сохраняем {description}, тип данных: {type(image_data)}")
    
    try:
        # Определяем тип данных и преобразуем в bytes
        if isinstance(image_data, str):
            if image_data.startswith('http'):
                # Это URL - скачиваем изображение
                logging.info(f"Обнаружен URL: {image_data}")
                return await download_image(image_data)
            else:
                # Это base64 - декодируем
                logging.info("Обнаружены base64 данные, декодируем...")
                import base64
                binary_data = base64.b64decode(image_data)
        elif isinstance(image_data, (bytes, bytearray)):
            # Уже бинарные данные
            logging.info("Обнаружены бинарные данные")
            binary_data = bytes(image_data)
        else:
            logging.error(f"Неизвестный тип данных изображения: {type(image_data)}")
            return None
        
        # Проверяем что данные не пустые
        if not binary_data:
            logging.error("Пустые данные изображения")
            return None
        
        logging.info(f"Размер данных для сохранения: {len(binary_data)} байт")
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
            f.write(binary_data)
            f.flush()
            temp_path = f.name
            
        # Проверяем что файл создан успешно
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            logging.info(f"{description} сохранено успешно: {temp_path}, размер: {os.path.getsize(temp_path)} байт")
            return temp_path
        else:
            logging.error(f"Файл не создан или пустой: {temp_path}")
            return None
            
    except Exception as e:
        logging.error(f"Ошибка сохранения {description}: {e}")
        return None

async def download_image(image_url):
    """Скачать изображение по URL"""
    logging.info(f"Скачиваем изображение с URL: {image_url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    logging.info(f"Размер скачанного изображения: {len(content)} байт")
                    
                    # Используем универсальную функцию сохранения
                    return await save_image_data(content, "скачанное изображение")
                else:
                    error_text = await resp.text()
                    logging.error(f"Ошибка скачивания изображения (status {resp.status}): {error_text}")
                    return None
    except Exception as e:
        logging.error(f"Исключение при скачивании изображения: {e}")
        return None

# --- Хэндлеры ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reset_user(user_id)
    await update.message.reply_text(
        "Привет! Давай придумаем сказку. Кто будет главным героем?",
        reply_markup=build_keyboard(HEROES)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Этот бот поможет придумать сказку на ночь с красивыми иллюстрациями! " \
        "Используй /new чтобы начать заново. " \
        "Используй /audio, чтобы получить аудиофайл сказки."
    )

async def new_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = USER_STATE.get(user_id)
    if not state:
        reset_user(user_id)
        state = USER_STATE[user_id]

    step = state['step']
    data = query.data

    if step == 'hero':
        if data == 'custom':
            state['step'] = 'hero_custom'
            await query.edit_message_text("Введи имя главного героя:")
            return
        state['hero'] = data
        state['step'] = 'place'
        await query.edit_message_text(
            "Где будет происходить действие?",
            reply_markup=build_keyboard(PLACES)
        )
    elif step == 'place':
        if data == 'custom':
            state['step'] = 'place_custom'
            await query.edit_message_text("Введи место действия:")
            return
        state['place'] = data
        state['step'] = 'mood'
        await query.edit_message_text(
            "Какое настроение у сказки?",
            reply_markup=build_keyboard(MOODS)
        )
    elif step == 'mood':
        state['mood'] = data
        state['step'] = 'age'
        await query.edit_message_text(
            "Для кого эта сказка?",
            reply_markup=build_keyboard(AGES)
        )
    elif step == 'age':
        state['age'] = data
        state['step'] = 'length'
        await query.edit_message_text(
            "Какой длины должна быть сказка?",
            reply_markup=build_keyboard(LENGTHS)
        )
    elif step == 'length':
        state['length'] = data
        state['step'] = 'done'
        await query.edit_message_text("Готовлю сказку с изображениями...")
        
        # Показываем действие "печатает..."
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        
        # Генерируем первое изображение на основе параметров
        try:
            initial_prompt = create_image_prompt(state)
            logging.info(f"Генерируем начальное изображение: {initial_prompt}")
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action="upload_photo")
            
            image_path = await generate_image(initial_prompt)
            logging.info(f"Получен путь к изображению: {image_path}")
            
            if image_path:
                logging.info(f"Отправляем изображение: {image_path}")
                try:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=query.message.chat_id, 
                            photo=photo, 
                            caption="🎨 Вот ваша сказка начинается..."
                        )
                        logging.info("Изображение успешно отправлено")
                        
                    # Удаляем временный файл
                    try:
                        os.unlink(image_path)
                        logging.info(f"Временный файл удален: {image_path}")
                    except Exception as e:
                        logging.warning(f"Не удалось удалить временный файл {image_path}: {e}")
                        
                except Exception as send_error:
                    logging.error(f"Ошибка отправки изображения в Telegram: {send_error}")
                    await context.bot.send_message(chat_id=query.message.chat_id, text="🎨 Начинаем сказку...")
            else:
                logging.error("Не удалось скачать изображение")
                await context.bot.send_message(chat_id=query.message.chat_id, text="🎨 Начинаем сказку...")
                
        except Exception as e:
            logging.error(f"Ошибка генерации начального изображения: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text="🎨 Начинаем сказку...")
        
        # Генерируем сказку
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        prompt = get_prompt(state)
        try:
            story = generate_story(prompt)
        except Exception as e:
            await query.edit_message_text(f"Не удалось сгенерировать сказку, простите. Попробуйте позже.")
            logging.error(f"Ошибка генерации сказки: {e}")
            return
        
        # Разделяем сказку на части
        story_parts = split_story_into_sentences(story)
        await query.edit_message_text("Готово! Вот твоя сказка:")
        
        # Отправляем каждую часть с изображением
        for i, part in enumerate(story_parts):
            # Отправляем текст части
            await context.bot.send_message(chat_id=query.message.chat_id, text=part)
            
            # Генерируем изображение для каждой части (включая последнюю)
            try:
                await context.bot.send_chat_action(chat_id=query.message.chat_id, action="upload_photo")
                image_prompt = create_image_prompt(state, part)
                logging.info(f"Генерируем изображение для части {i+1}: {image_prompt[:100]}...")
                image_path = await generate_image(image_prompt)
                logging.info(f"Получен путь к изображению для части {i+1}: {image_path}")
                
                if image_path:
                    logging.info(f"Отправляем изображение части {i+1}: {image_path}")
                    try:
                        # Определяем подпись для изображения
                        if i == len(story_parts) - 1:
                            caption = "🎨 Конец сказки"
                        else:
                            caption = f"🎨 Часть {i+2}"
                            
                        with open(image_path, 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=query.message.chat_id, 
                                photo=photo, 
                                caption=caption
                            )
                            logging.info(f"Изображение части {i+1} успешно отправлено")
                            
                        # Удаляем временный файл
                        try:
                            os.unlink(image_path)
                            logging.info(f"Временный файл части {i+1} удален: {image_path}")
                        except Exception as e:
                            logging.warning(f"Не удалось удалить временный файл {image_path}: {e}")
                            
                    except Exception as send_error:
                        logging.error(f"Ошибка отправки изображения части {i+1} в Telegram: {send_error}")
                else:
                    logging.error(f"Не удалось скачать изображение для части {i+1}")
                    
            except Exception as e:
                logging.error(f"Ошибка генерации изображения для части {i+1}: {e}")
                # Продолжаем без изображения
        
        # Сохраняем последнюю сказку пользователя
        USER_STORY[user_id] = story

# --- Тестовая команда для отладки генерации изображений ---
async def test_image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Генерирую тестовое изображение...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    try:
        test_prompt = "детская книжная иллюстрация: маленький дракончик в волшебном лесу, добрая атмосфера, яркие цвета"
        logging.info(f"Генерируем тестовое изображение: {test_prompt}")
        image_path = await generate_image(test_prompt)
        logging.info(f"Получен путь к тестовому изображению: {image_path}")
        
        if image_path:
            logging.info(f"Отправляем тестовое изображение: {image_path}")
            try:
                with open(image_path, 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id, 
                        photo=photo, 
                        caption="🎨 Тестовое изображение"
                    )
                    logging.info("Тестовое изображение успешно отправлено")
                    
                # Удаляем временный файл
                try:
                    os.unlink(image_path)
                    logging.info(f"Временный тестовый файл удален: {image_path}")
                except Exception as e:
                    logging.warning(f"Не удалось удалить временный файл {image_path}: {e}")
                    
            except Exception as send_error:
                logging.error(f"Ошибка отправки тестового изображения в Telegram: {send_error}")
                await update.message.reply_text(f"Изображение сгенерировано, но не отправлено: {send_error}")
        else:
            logging.error("Не удалось скачать тестовое изображение")
            await update.message.reply_text("Не удалось скачать сгенерированное изображение")
    except Exception as e:
        logging.error(f"Ошибка генерации тестового изображения: {e}")
        await update.message.reply_text(f"Ошибка генерации изображения: {e}")
        logging.error(f"Ошибка тестовой генерации изображения: {e}")

# --- Команда для проверки конфигурации ---
async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global iam_token
    debug_info = []
    
    # Проверяем переменные окружения
    debug_info.append(f"YANDEX_FOLDER_ID: {'✅ настроен' if folder_id else '❌ не настроен'}")
    debug_info.append(f"NEUROAPI_API_KEY: {'✅ настроен' if NEUROAPI_API_KEY else '❌ не настроен'}")
    
    # Проверяем IAM токен
    if not iam_token:
        iam_token = fetch_iam_token()
    
    if iam_token:
        debug_info.append(f"IAM токен: ✅ получен (длина: {len(iam_token)})")
    else:
        debug_info.append("IAM токен: ❌ не получен")
    
    # Проверяем конфигурацию для Art API
    if folder_id and iam_token:
        debug_info.append(f"Model URI: art://{folder_id}/yandex-art/latest")
        debug_info.append(f"Art API URL: {YANDEX_ART_URL}")
    
    await update.message.reply_text("\n".join(debug_info))

# --- Тестовая команда для отладки TTS ---
async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_text = (
        "Конечно, вот добрая сказка на ночь для вашего малыша.\n\n"
        "### Приключения Дракончика Искорки\n\n"
        "В одном удивительном городе будущего, где дома были похожи на хрустальные небоскрёбы, а по небу вместо машин летали разноцветные аэромобили, жил-был маленький дракончик. Звали его Искорка. Он был совсем не страшный. Вместо огня он умел выдыхать тёплые мыльные пузыри, которые светились всеми цветами радуги и пахли клубничной газировкой.\n\n"
        "Жил Искорка со своими мамой и папой в уютной пещерке на самой вершине самого высокого здания. Каждый вечер он любил сидеть на своём облачном балкончике и смотреть, как город готовится ко сну. Аэромобили тихонько парковались в свои воздушные гаражи, роботы-садовники поливали лунные цветы, которые начинали светиться в темноте, а в окнах домов зажигались огоньки-ночники.\n\n"
        "Сегодня Искорке было особенно весело. Весь день он играл в догонялки с ветром и кувыркался в пушистых облаках. Но вот наступил вечер, и мама-дракониха сказала: «Искорка, пора спать».\n\n"
        "Но дракончику совсем не хотелось спать! Ему хотелось сделать что-нибудь доброе и волшебное для всего города. И он придумал!\n\n"
        "Он тихонько вылетел со своего балкона, подлетел к большому круглому окну, за которым грустил маленький мальчик, и тихонько дунул. Пух! Из ноздрей Искорки вылетел огромный радужный пузырь. Он подплыл к окну, легонько стукнулся о стекло и лопнул с тихим звуком «бульк!», оставив после себя запах клубники и россыпь крошечных блёсток. Мальчик за окном улыбнулся и помахал Искорке рукой.\n\n"
        "Дракончик обрадовался и полетел дальше. Он пролетал над парками, где роботы-няни укладывали спать маленьких зверят, и дарил всем по одному светящемуся пузырю. Весь город наполнился нежным светом и сладким ароматом. Все вокруг улыбались, зевали и потихоньку засыпали.\n\n"
        "Сделав свой большой добрый круг, Искорка почувствовал, что и его глазки стали слипаться. Он вернулся в свою пещерку, где его уже ждала мама. Она укрыла его тёплым крылом, поцеловала в носик и прошептала: «Мой маленький волшебник».\n\n"
        "Искорка уютно свернулся калачиком, в последний раз улыбнулся, вспоминая счастливые лица жителей, и сладко-сладко заснул. И ему приснились самые радужные и клубничные сны.\n\n"
        "И тебе, малыш, пора спать. Закрывай глазки и пусть тебе приснятся такие же добрые и весёлые сны. Сладких снов"
    )
    await update.message.reply_text("Готовлю тестовое аудио...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.RECORD_VOICE)
    try:
        ogg_path, mp3_path = await synthesize_tts(test_text, folder_id)
        with open(ogg_path, 'rb') as voice:
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=voice)
        if mp3_path and os.path.exists(mp3_path):
            with open(mp3_path, 'rb') as audio:
                await context.bot.send_audio(chat_id=update.effective_chat.id, audio=audio, filename='test.mp3')
    except Exception as e:
        if str(e) == 'TTS_TEXT_TOO_LONG':
            await update.message.reply_text("Эта сказка слишком длинная. Я не смогу ее прочитать.")
        else:
            await update.message.reply_text(f"Ошибка синтеза: {e}")

async def synthesize_tts(text, folder_id):
    global iam_token
    # Получаем актуальный IAM токен
    if not iam_token:
        iam_token = fetch_iam_token()
        if not iam_token:
            raise Exception('Не удалось получить IAM токен')
    url = 'https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize'
    headers = {
        'Authorization': 'Bearer ' + iam_token,
    }
    data = {
        'text': text,
        'lang': 'ru-RU',
        'voice': 'jane',
        'emotion': 'good',
        'folderId': folder_id,
        'format': 'oggopus',
        'sampleRateHertz': 48000
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=data) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                if 'Requested text length exceed limitation' in err_text:
                    raise Exception('TTS_TEXT_TOO_LONG')
                raise Exception(f"TTS error: {err_text}")
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as f:
                content = await resp.read()
                if not content:
                    raise Exception("TTS API вернул пустой аудиофайл. Попробуйте другой текст или повторите попытку позже.")
                f.write(content)
                ogg_path = f.name
    # Конвертация oggopus -> mp3 через ffmpeg
    mp3_path = ogg_path.replace('.ogg', '.mp3')
    try:
        result = subprocess.run([
            'ffmpeg', '-y', '-i', ogg_path, '-acodec', 'libmp3lame', mp3_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or not os.path.exists(mp3_path):
            logging.error(f"ffmpeg error: {result.stderr.decode('utf-8')}")
            mp3_path = None
    except Exception as e:
        logging.error(f"ffmpeg exception: {e}")
        mp3_path = None
    return ogg_path, mp3_path

# --- Команда /audio ---
async def audio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    story = USER_STORY.get(user_id)
    state = USER_STATE.get(user_id)
    if not story:
        await update.message.reply_text("Сначала сгенерируйте сказку командой /start или /new.")
        return
    await update.message.reply_text("Готовлю аудиофайл...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.RECORD_VOICE)
    try:
        if state and state.get('length') == 'long':
            mid = len(story) // 2
            split_idx = story.rfind('.', 0, mid)
            if split_idx == -1:
                split_idx = story.rfind(' ', 0, mid)
            if split_idx == -1:
                split_idx = mid
            part1 = story[:split_idx+1].strip()
            part2 = story[split_idx+1:].strip()
            ogg_path1, _ = await synthesize_tts(part1, folder_id)
            with open(ogg_path1, 'rb') as voice1:
                await context.bot.send_voice(chat_id=update.effective_chat.id, voice=voice1)
            ogg_path2, _ = await synthesize_tts(part2, folder_id)
            with open(ogg_path2, 'rb') as voice2:
                await context.bot.send_voice(chat_id=update.effective_chat.id, voice=voice2)
        else:
            ogg_path, _ = await synthesize_tts(story, folder_id)
            with open(ogg_path, 'rb') as voice:
                await context.bot.send_voice(chat_id=update.effective_chat.id, voice=voice)
    except Exception as e:
        if str(e) == 'TTS_TEXT_TOO_LONG':
            await update.message.reply_text("Эта сказка слишком длинная. Я не смогу ее прочитать.")
        else:
            await update.message.reply_text(f"Не удалось синтезировать аудио, простите. Попробуйте позже.")
            logging.error(f"Ошибка синтеза аудио: {e}")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id)
    if not state:
        return
    step = state['step']
    text = update.message.text.strip()
    if step == 'hero_custom':
        state['hero'] = text
        state['step'] = 'place'
        await update.message.reply_text(
            "Где будет происходить действие?",
            reply_markup=build_keyboard(PLACES)
        )
    elif step == 'place_custom':
        state['place'] = text
        state['step'] = 'mood'
        await update.message.reply_text(
            "Какое настроение у сказки?",
            reply_markup=build_keyboard(MOODS)
        )

# --- Main ---
def main():
    # Запускаем обновление IAM токена
    schedule_iam_token_update()
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('new', new_cmd))
    app.add_handler(CommandHandler('audio', audio_cmd))
    app.add_handler(CommandHandler('test', test_cmd))
    app.add_handler(CommandHandler('testimg', test_image_cmd))
    app.add_handler(CommandHandler('debug', debug_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()

if __name__ == '__main__':
    main()
