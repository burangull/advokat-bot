import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# ─── НАСТРОЙКИ (читаются из переменных окружения Render) ───
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
PORT = int(os.getenv("PORT", 8080))

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная TELEGRAM_BOT_TOKEN")
if not GROUP_CHAT_ID:
    raise RuntimeError("Не задана переменная GROUP_CHAT_ID")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ─── СОСТОЯНИЯ ДИАЛОГА ─────────────────────────────
class Form(StatesGroup):
    topic = State()
    situation = State()
    region = State()
    phone = State()


# ─── ТЕМЫ ОБРАЩЕНИЙ ────────────────────────────────
TOPICS = {
    "topic_1": "Консультация в сфере военного права",
    "topic_2": "Содействие в получении выплат и компенсаций",
    "topic_3": "Помощь в процедуре увольнения",
    "topic_4": "Сопровождение лиц, допустивших дезертирство или СОЧ",
    "topic_5": "Поддержка при прохождении ВВК, обжалование неправомерных решений",
    "topic_6": "Сопровождение военнослужащих, обвиняемых или подозреваемых в совершении преступления",
    "topic_7": "Жалобы на бездействия при розыске без вести пропавших (БП) или освобождении военнопленного",
    "topic_8": "Другое",
}


# ─── ХЕЛПЕРЫ ───────────────────────────────────────
def greeting() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    return "Добрый вечер"


def topics_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"✅ {name}", callback_data=key)]
        for key, name in TOPICS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ─── /start ────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"{greeting()}! 👋\n\n"
        "<b>Чем именно вам помочь?</b> Выберите подходящую тему:",
        reply_markup=topics_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(Form.topic)


# ─── ВЫБОР ТЕМЫ ────────────────────────────────────
@dp.callback_query(StateFilter(Form.topic), F.data.startswith("topic_"))
async def choose_topic(callback: types.CallbackQuery, state: FSMContext):
    topic = TOPICS.get(callback.data)
    if not topic:
        await callback.answer("Пожалуйста, выберите тему из списка.")
        return

    await state.update_data(topic=topic)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Вы выбрали: <b>{topic}</b>\n\n"
        "Опишите кратко вашу ситуацию (в одном сообщении):",
        parse_mode="HTML",
    )
    await state.set_state(Form.situation)
    await callback.answer()


# ─── СИТУАЦИЯ ──────────────────────────────────────
@dp.message(StateFilter(Form.situation))
async def get_situation(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 3:
        await message.answer("Пожалуйста, опишите ситуацию текстом (минимум пару слов).")
        return
    await state.update_data(situation=message.text)
    await message.answer(
        "Укажите ваш регион/город (это важно для определения юрисдикции):"
    )
    await state.set_state(Form.region)


# ─── РЕГИОН ────────────────────────────────────────
@dp.message(StateFilter(Form.region))
async def get_region(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 2:
        await message.answer("Пожалуйста, укажите ваш регион или город.")
        return
    await state.update_data(region=message.text)
    await message.answer(
        "Оставьте ваш номер телефона для связи или нажмите кнопку ниже, "
        "чтобы поделиться текущим номером.\n\n"
        "<i>(Если не хотите — напишите любую цифру)</i>",
        reply_markup=phone_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(Form.phone)


# ─── ТЕЛЕФОН: КОНТАКТОМ ────────────────────────────
@dp.message(StateFilter(Form.phone), F.contact)
async def get_phone_contact(message: types.Message, state: FSMContext):
    await finish_form(message, state, phone=message.contact.phone_number)


# ─── ТЕЛЕФОН: ТЕКСТОМ или ОТКАЗ ────────────────────
@dp.message(StateFilter(Form.phone))
async def get_phone_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пожалуйста, отправьте номер или нажмите кнопку ниже.")
        return

    if len(text) == 1 and text.isdigit():
        await finish_form(message, state, phone="— (не указан)")
        return

    await finish_form(message, state, phone=text)


# ─── ФИНАЛ ─────────────────────────────────────────
async def finish_form(message: types.Message, state: FSMContext, phone: str):
    data = await state.get_data()
    await state.update_data(phone=phone)

    await message.answer(
        "Спасибо. В течение дня с вами свяжется наш военный адвокат.\n\n"
        "Все обращения строго конфиденциальны и защищены адвокатской тайной.",
        reply_markup=ReplyKeyboardRemove(),
    )

    notify = (
        "🆕 <b>Новая заявка</b>\n\n"
        f"<b>Тема:</b> {data.get('topic', '—')}\n"
        f"<b>Ситуация:</b> {data.get('situation', '—')}\n"
        f"<b>Регион/город:</b> {data.get('region', '—')}\n"
        f"<b>Телефон:</b> {phone}\n"
        f"<b>User:</b> @{message.from_user.username or '—'} "
        f"(id: {message.from_user.id})"
    )
    try:
        await bot.send_message(GROUP_CHAT_ID, notify, parse_mode="HTML")
    except Exception as e:
        print(f"ОШИБКА отправки в группу: {e}")

    await state.clear()


# ─── ВЕБ-СЕРВЕР ДЛЯ RENDER ─────────────────────────
async def health(request: web.Request) -> web.Response:
    """Эндпоинт для self-ping — чтобы Render не засыпал."""
    return web.Response(text="OK")


async def on_startup(app: web.Application):
    """Устанавливаем вебхук при старте приложения."""
    public_url = os.getenv("RENDER_EXTERNAL_URL")  # Render подставит сам
    if public_url:
        await bot.set_webhook(f"{public_url}/webhook", drop_pending_updates=True)
        print(f"Вебхук установлен: {public_url}/webhook")
    else:
        print("RENDER_EXTERNAL_URL не найден — вебхук не установлен")


async def on_shutdown(app: web.Application):
    """Корректно закрываем сессию бота при остановке."""
    await bot.session.close()


def main():
    app = web.Application()

    # Эндпоинт для healthcheck и self-ping
    app.router.add_get("/", health)

    # Обработчик вебхуков от Telegram
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")

    # События старта/остановки
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # setup_application нужен для корректной работы aiogram (middleware, etc.)
    setup_application(app, dp, bot=bot)

    print(f"Запуск веб-сервера на 0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()