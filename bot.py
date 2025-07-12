import os
import logging
import tempfile
import requests
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
)
from telegram.constants import ChatAction
import subprocess

# --- Конфиг ---
NEUROAPI_API_KEY = os.getenv('NEUROAPI_API_KEY')
NEUROAPI_URL = 'https://neuroapi.host/v1/chat/completions'
MODEL = 'gemini-2.5-pro'

folder_id = os.getenv('YANDEX_FOLDER_ID')
# iam_token теперь будет обновляться автоматически
iam_token = None

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

def schedule_iam_token_update():
    global iam_token
    def update_token():
        global iam_token
        token = fetch_iam_token()
        if token:
            iam_token = token
    update_token()  # Получить токен при запуске
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_token, 'interval', hours=24)
    # Чтобы планировщик работал в фоне
    threading.Thread(target=scheduler.start, daemon=True).start()

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
        "Этот бот поможет придумать сказку на ночь. " \
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
        await query.edit_message_text("Готовлю сказку...")
        # Показываем действие "печатает..."
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action="typing")
        prompt = get_prompt(state)
        try:
            story = generate_story(prompt)
        except Exception as e:
            await query.edit_message_text(f"Не удалось сгенерировать сказку, простите. Попробуйте позже.")
            logging.error(f"Ошибка генерации сказки: {e}")
            return
        # Отправляем сказку частями, если она длинная
        max_len = 4096
        parts = [story[i:i+max_len] for i in range(0, len(story), max_len)]
        await query.edit_message_text("Готово! Вот твоя сказка:")
        for part in parts:
            await context.bot.send_message(chat_id=query.message.chat_id, text=part)
        # Сохраняем последнюю сказку пользователя
        USER_STORY[user_id] = story

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
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()

if __name__ == '__main__':
    main()
