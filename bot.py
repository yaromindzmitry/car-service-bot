import os
import logging
import re
from datetime import datetime, timedelta, time
from dateutil.parser import parse as parse_datetime
from dateutil.parser import isoparse
import pytz
from openai import OpenAI
from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChatMember, BotCommandScopeChatAdministrators
from collections import defaultdict
from telegram import ReplyKeyboardMarkup
from ai_diagnostic_agent import handle_assistant, handle_user_message

from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, ContextTypes, filters
)
from telegram.ext import ConversationHandler
LANGUAGE, AUTO, YEAR, VIN, TELEFON, OPIS, SLOT_SELECT = range(7)

import nest_asyncio
nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

assistant_system_prompts = {
    "🇷🇺 Русский": "Ты — опытный автоэлектрик и механик. Помогаешь определить неисправности автомобиля по описанию. Уточняешь симптомы, даешь советы. Отвечай на русском.",
    "🇵🇱 Polski": "Jesteś doświadczonym mechanikiem samochodowym. Pomagasz zidentyfikować problemy na podstawie opisu. Zadawaj pytania, dawaj porady. Odpowiadaj po polsku.",
    "🇬🇧 English": "You are an experienced car mechanic. You help diagnose vehicle issues based on user input. Ask clarifying questions and provide suggestions. Answer in English."
}

admin_button_text = {
    "🇷🇺 Русский": "♻️ Обновить данные",
    "🇵🇱 Polski": "♻️ Odśwież dane",
    "🇬🇧 English": "♻️ Reload data"
}

# Загрузка .env
load_dotenv(dotenv_path=".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB")
CREDENTIALS_SHEET = os.getenv("GOOGLE_CREDENTIALS_PATH")
CREDENTIALS_CALENDAR = os.getenv("GOOGLE_CREDENTIALS_CALENDAR")
CALENDAR_ID = os.getenv("CALENDAR_ID")
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

if not CALENDAR_ID:
    raise ValueError("❌ Не найден CALENDAR_ID. Убедись, что он указан в .env")

# Подключение Google Sheets
sheet_creds = Credentials.from_service_account_file(CREDENTIALS_SHEET, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
sheet_client = gspread.authorize(sheet_creds)
sheet = sheet_client.open(SHEET_NAME).worksheet(SHEET_TAB)

# Подключение Google Calendar
calendar_creds = Credentials.from_service_account_file(CREDENTIALS_CALENDAR, scopes=[
    "https://www.googleapis.com/auth/calendar"
])
calendar_service = build("calendar", "v3", credentials=calendar_creds)

# Константы состояний
LANGUAGE, AUTO, YEAR, VIN, TELEFON, OPIS, SLOT_SELECT = range(7)

async def slot_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ✅ Привязка к timezone
    tz = pytz.timezone("Europe/Warsaw")
    slot_start = isoparse(query.data).replace(tzinfo=None)
    slot_start = tz.localize(slot_start)
    slot_end = slot_start + timedelta(minutes=30)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    # Получаем язык пользователя из таблицы
    lang = None
    subscribed = False
    try:
        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        rows = sub_sheet.get_all_values()[1:]
        for row in rows:
            if row[0] == user_id:
                lang = row[1]
                subscribed = True
                break
    except Exception as e:
        logging.warning("⚠️ Ошибка при проверке подписки при старте: %s", e)

    # Если язык не найден — показать выбор
    if not lang:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("🇵🇱 Polski", callback_data="lang_pl")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ])
        await update.message.reply_text(
            "Выберите язык / Choose language / Wybierz język:",
            reply_markup=keyboard
        )
        return

    # Сохраняем язык в сессию
    context.user_data["lang"] = lang

    subscribe_text = {
        "🇷🇺 Русский": "📬 Отписаться" if subscribed else "📬 Подписаться",
        "🇵🇱 Polski": "📬 Wypisz się" if subscribed else "📬 Subskrybuj",
        "🇬🇧 English": "📬 Unsubscribe" if subscribed else "📬 Subscribe"
    }.get(lang, "📬 Подписаться")

    promo = PROMO_MESSAGES.get(lang, "Добро пожаловать!")

    if lang == "🇵🇱 Polski":
        buttons = [
            [InlineKeyboardButton("📍 Adres", callback_data="address"),
             InlineKeyboardButton("📝 Rejestracja", callback_data="zapis")],
            [InlineKeyboardButton("📞 Kontakt", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Asystent diagnostyczny", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Zmień język", callback_data="change_language")]
        ]
    elif lang == "🇬🇧 English":
        buttons = [
            [InlineKeyboardButton("📍 Address", callback_data="address"),
             InlineKeyboardButton("📝 Appointment", callback_data="zapis")],
            [InlineKeyboardButton("📞 Contact", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Assistant", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Change language", callback_data="change_language")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📍 Адрес", callback_data="address"),
             InlineKeyboardButton("📝 Запись", callback_data="zapis")],
            [InlineKeyboardButton("📞 Контакты", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Помощник по неисправностям", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Сменить язык", callback_data="change_language")]
        ]

    # 👑 Админ-кнопка
    if str(update.effective_user.id) == str(ADMIN_ID):
        admin_text = admin_button_text.get(lang, "♻️ Обновить данные")
        buttons.append([InlineKeyboardButton(admin_text, callback_data="reload_all")])
        buttons.append([InlineKeyboardButton("📢 Разослать новость", callback_data="send_news")])

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(promo, reply_markup=keyboard)

    # Если язык найден — сохранить и показать меню
async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang_map = {
        "lang_ru": "🇷🇺 Русский",
        "lang_pl": "🇵🇱 Polski",
        "lang_en": "🇬🇧 English"
    }

    callback_data = query.data
    lang = lang_map.get(callback_data, "🇷🇺 Русский")
    context.user_data["lang"] = lang

    user_id = str(query.from_user.id)
    subscribed = False

    try:
        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        all_ids = [row[0] for row in sub_sheet.get_all_values()[1:]]
        subscribed = user_id in all_ids
        if not subscribed:
            sub_sheet.append_row([user_id, lang])
    except Exception as e:
        logging.warning("⚠️ Не удалось проверить или добавить подписку: %s", e)

    # Динамический текст кнопки подписки
    subscribe_text = {
        "🇷🇺 Русский": "📬 Отписаться" if subscribed else "📬 Подписаться",
        "🇵🇱 Polski": "📬 Wypisz się" if subscribed else "📬 Subskrybuj",
        "🇬🇧 English": "📬 Unsubscribe" if subscribed else "📬 Subscribe"
    }.get(lang, "📬 Подписаться")

    promo = PROMO_MESSAGES.get(lang, "Добро пожаловать!")

    if lang == "🇵🇱 Polski":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Adres", callback_data="address"),
             InlineKeyboardButton("📝 Rejestracja", callback_data="zapis")],
            [InlineKeyboardButton("📞 Kontakt", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Asystent diagnostyczny", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Zmień język", callback_data="change_language")]
        ])
    elif lang == "🇬🇧 English":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Address", callback_data="address"),
             InlineKeyboardButton("📝 Appointment", callback_data="zapis")],
            [InlineKeyboardButton("📞 Contact", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Assistant", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Change language", callback_data="change_language")]
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Адрес", callback_data="address"),
             InlineKeyboardButton("📝 Запись", callback_data="zapis")],
            [InlineKeyboardButton("📞 Контакты", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Помощник по неисправностям", callback_data="assistant")],
            [InlineKeyboardButton("🌍 Сменить язык", callback_data="change_language")]
        ])

    await update.message.reply_text(promo, reply_markup=keyboard)

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇵🇱 Polski", callback_data="lang_pl")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
    ])
    await query.edit_message_text(
        "Выберите язык / Choose language / Wybierz język:",
        reply_markup=keyboard
    )

    await query.edit_message_text(
    "Выберите язык / Choose language / Wybierz język:",
    reply_markup=keyboard
)

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang_map = {
        "lang_ru": "🇷🇺 Русский",
        "lang_pl": "🇵🇱 Polski",
        "lang_en": "🇬🇧 English"
    }

    callback_data = query.data
    lang = lang_map.get(callback_data, "🇷🇺 Русский")
    context.user_data["lang"] = lang

    user_id = str(query.from_user.id)
    subscribed = False

    try:
        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        all_ids = [row[0] for row in sub_sheet.get_all_values()[1:]]
        subscribed = user_id in all_ids
        if not subscribed:
            sub_sheet.append_row([user_id, lang])
    except Exception as e:
        logging.warning("⚠️ Не удалось проверить или добавить подписку: %s", e)

    # Динамический текст кнопки подписки
    subscribe_text = {
        "🇷🇺 Русский": "📬 Отписаться" if subscribed else "📬 Подписаться",
        "🇵🇱 Polski": "📬 Wypisz się" if subscribed else "📬 Subskrybuj",
        "🇬🇧 English": "📬 Unsubscribe" if subscribed else "📬 Subscribe"
    }.get(lang, "📬 Подписаться")

    # Получаем текст из Google Таблицы
    text = PROMO_MESSAGES.get(lang, "Добро пожаловать!")

    if lang == "🇵🇱 Polski":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Adres", callback_data="address"),
             InlineKeyboardButton("📝 Rejestracja", callback_data="zapis")],
            [InlineKeyboardButton("📞 Kontakt", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Asystent awarii", callback_data="assistant")]
        ])
    elif lang == "🇬🇧 English":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Address", callback_data="address"),
             InlineKeyboardButton("📝 Appointment", callback_data="zapis")],
            [InlineKeyboardButton("📞 Contact", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Assistant", callback_data="assistant")]
        ])
    else:  # Русский по умолчанию
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 Адрес", callback_data="address"),
             InlineKeyboardButton("📝 Запись", callback_data="zapis")],
            [InlineKeyboardButton("📞 Контакты", callback_data="contacts"),
             InlineKeyboardButton(subscribe_text, callback_data="subscribe")],
            [InlineKeyboardButton("🤖 Помощник по неисправностям", callback_data="assistant")]
        ])

    await query.edit_message_text(text=text, reply_markup=keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "send_news":
        await send_news(update, context)
        return

    if data == "address":
        await show_address(update, context)
    elif data == "zapis":
        return await conv_handler.entry_points[0].callback(update, context)
    elif data == "contacts":
        await show_contacts(update, context)
    elif data == "subscribe":
        await toggle_subscription(update, context)
    elif data == "assistant":
        await handle_assistant(update, context)
    elif data == "reload_all":
        await reload_all(update, context)

    # Сбор сообщений
    lang = context.user_data.get("lang", "🇷🇺 Русский")
    system_prompt = assistant_system_prompts.get(lang, assistant_system_prompts["🇷🇺 Русский"])
    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": user_input}
    ]

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content

        # Обновляем историю
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})
        context.user_data["assistant_history"] = history

    except Exception as e:
        logging.error("Ошибка OpenAI: %s", e)
        reply = {
            "🇷🇺 Русский": "⚠️ Произошла ошибка. Попробуйте позже.",
            "🇵🇱 Polski": "⚠️ Wystąpił błąd. Spróbuj ponownie później.",
            "🇬🇧 English": "⚠️ An error occurred. Please try again later."
        }.get(lang, "⚠️ Ошибка. Попробуйте позже.")

    await update.message.reply_text(reply)

async def toggle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    try:
        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        values = sub_sheet.get_all_values()
        rows = values[1:]  # без заголовка
        ids = [row[0] for row in rows]

        if user_id in ids:
            index = ids.index(user_id) + 2  # +2 из-за заголовка и индекса с 1
            sub_sheet.delete_rows(index)
            status_msg = "❌ Вы отписались от новостей."
        else:
            sub_sheet.append_row([user_id, lang])
            status_msg = "✅ Вы подписались на новости."

        await query.answer()

        # Сначала отправим статус
        await context.bot.send_message(chat_id=query.message.chat_id, text=status_msg)

        # Затем обновим меню
        await back_to_menu(update, context)

    except Exception as e:
        logging.error("❌ Ошибка при работе с подпиской: %s", e)
        await query.answer("⚠️ Ошибка. Попробуйте позже.")
        
async def show_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CONTACTS
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    address = CONTACTS.get("ADDRESS", "Gdańsk")
    try:
        latitude = float(CONTACTS.get("LAT", "0"))
        longitude = float(CONTACTS.get("LNG", "0"))
    except ValueError:
        latitude, longitude = 0.0, 0.0
        logging.error("❌ Невалидные координаты LAT/LNG")

    await update.effective_message.reply_location(latitude=latitude, longitude=longitude)

    route_url = f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"

    route_button_text = {
        "🇷🇺 Русский": "🗺️ Проложить маршрут",
        "🇵🇱 Polski": "🗺️ Wyznacz trasę",
        "🇬🇧 English": "🗺️ Get directions"
    }.get(lang, "🗺️ Проложить маршрут")

    await update.effective_message.reply_text(
        f"📍 {address}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(route_button_text, url=route_url)]
        ])
    )

async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CONTACTS
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    phone = CONTACTS.get("PHONE", "+48 000 000 000")
    instagram = CONTACTS.get("INSTAGRAM", "#")
    facebook = CONTACTS.get("FACEBOOK", "#")

    text_map = {
        "🇷🇺 Русский": f"Наши контакты и соцсети:\n\n📞 Телефон: {phone}",
        "🇵🇱 Polski": f"Nasze kontakty i media społecznościowe:\n\n📞 Telefon: {phone}",
        "🇬🇧 English": f"Our contacts and social media:\n\n📞 Phone: {phone}"
    }

    back_label = {
        "🇷🇺 Русский": "🔙 Назад",
        "🇵🇱 Polski": "🔙 Wróć",
        "🇬🇧 English": "🔙 Back"
    }.get(lang, "🔙 Назад")

    buttons = [
        [InlineKeyboardButton("📸 Instagram", url=instagram)],
        [InlineKeyboardButton("📘 Facebook", url=facebook)],
        [InlineKeyboardButton(back_label, callback_data="back_to_menu")]
    ]

    await update.effective_message.reply_text(
        text_map.get(lang, text_map["🇷🇺 Русский"]),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

LANGUAGE, AUTO, YEAR, VIN, TELEFON, OPIS, SLOT_SELECT = range(7)

async def get_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auto_input = update.message.text.strip()
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    parts = auto_input.split(maxsplit=1)
    if len(parts) < 2:
        error_msg = {
            "🇷🇺 Русский": "❌ Введите марку и модель через пробел, например: Audi A4",
            "🇵🇱 Polski": "❌ Wprowadź markę i model oddzielone spacją, np. Audi A4",
            "🇬🇧 English": "❌ Enter make and model separated by space, e.g. Audi A4"
        }.get(lang, "❌ Введите корректные данные: марка и модель")
        await update.message.reply_text(error_msg)
        return AUTO

    marka, model = parts[0], parts[1]

    if not re.match(r"^[A-Za-zА-Яа-яЁё]+$", marka):
        error_msg = {
            "🇷🇺 Русский": "❌ Марка должна содержать только буквы.",
            "🇵🇱 Polski": "❌ Marka może zawierać tylko litery.",
            "🇬🇧 English": "❌ Make must contain only letters."
        }.get(lang, "❌ Только буквы в марке")
        await update.message.reply_text(error_msg)
        return AUTO

    if not re.match(r"^[A-Za-zА-Яа-яЁё0-9]+$", model):
        error_msg = {
            "🇷🇺 Русский": "❌ Модель должна содержать только буквы и цифры.",
            "🇵🇱 Polski": "❌ Model może zawierać tylko litery i cyfry.",
            "🇬🇧 English": "❌ Model can only contain letters and digits."
        }.get(lang, "❌ Только буквы и цифры в модели")
        await update.message.reply_text(error_msg)
        return AUTO

    context.user_data["auto"] = f"{marka} {model}"

    next_msg = {
        "🇷🇺 Русский": "Год выпуска:",
        "🇵🇱 Polski": "Podaj rok produkcji:",
        "🇬🇧 English": "Enter the year of manufacture:"
    }.get(lang, "Год выпуска:")
    await update.message.reply_text(next_msg)
    return YEAR

async def handle_zapis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    return await get_auto(update.callback_query, context)

async def get_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year_input = update.message.text.strip()
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    if not year_input.isdigit() or len(year_input) != 4 or int(year_input) < 1990:
        error_msg = {
            "🇷🇺 Русский": "❌ Введите корректный год (4 цифры, не раньше 1990).",
            "🇵🇱 Polski": "❌ Wprowadź poprawny rok (4 cyfry, nie wcześniej niż 1990).",
            "🇬🇧 English": "❌ Enter a valid year (4 digits, not earlier than 1990)."
        }.get(lang, "❌ Неверный год")
        await update.message.reply_text(error_msg)
        return YEAR

    context.user_data["year"] = year_input

    next_msg = {
        "🇷🇺 Русский": "VIN код:",
        "🇵🇱 Polski": "Kod VIN:",
        "🇬🇧 English": "VIN code:"
    }.get(lang, "VIN код:")
    await update.message.reply_text(next_msg)
    return VIN

async def get_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vin_input = update.message.text.strip().upper()
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    if len(vin_input) != 17 or not re.match(r"^[A-HJ-NPR-Z0-9]{17}$", vin_input):
        error_msg = {
            "🇷🇺 Русский": "❌ VIN должен содержать ровно 17 символов (без I, O, Q).",
            "🇵🇱 Polski": "❌ VIN musi mieć dokładnie 17 znaków (bez I, O, Q).",
            "🇬🇧 English": "❌ VIN must be exactly 17 characters (excluding I, O, Q)."
        }.get(lang, "❌ Неверный VIN")
        await update.message.reply_text(error_msg)
        return VIN

    context.user_data["vin"] = vin_input

    next_msg = {
        "🇷🇺 Русский": "Введите номер телефона:",
        "🇵🇱 Polski": "Podaj numer telefonu:",
        "🇬🇧 English": "Enter your phone number:"
    }.get(lang, "Введите номер телефона:")
    await update.message.reply_text(next_msg)
    return TELEFON

async def get_telefon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_input = update.message.text.strip()
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    if not re.match(r"^\+?\d{9,15}$", phone_input):
        error_msg = {
            "🇷🇺 Русский": "❌ Введите корректный номер телефона (9–15 цифр).",
            "🇵🇱 Polski": "❌ Wprowadź poprawny numer telefonu (9–15 cyfr).",
            "🇬🇧 English": "❌ Enter a valid phone number (9–15 digits)."
        }.get(lang, "❌ Некорректный номер телефона")
        await update.message.reply_text(error_msg)
        return TELEFON

    context.user_data["telefon"] = phone_input

    next_msg = {
        "🇷🇺 Русский": "Опишите проблему:",
        "🇵🇱 Polski": "Opisz problem:",
        "🇬🇧 English": "Describe the issue:"
    }.get(lang, "Опишите проблему:")
    await update.message.reply_text(next_msg)
    return OPIS

async def get_telefon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_input = update.message.text.strip()
    lang = context.user_data.get("lang", "🇷🇺 Русский")

    if not re.match(r"^\+?\d{9,15}$", phone_input):
        error_msg = {
            "🇷🇺 Русский": "❌ Введите корректный номер телефона (9–15 цифр).",
            "🇵🇱 Polski": "❌ Wprowadź poprawny numer telefonu (9–15 cyfr).",
            "🇬🇧 English": "❌ Enter a valid phone number (9–15 digits)."
        }.get(lang)
        await update.message.reply_text(error_msg)
        return TELEFON

    context.user_data["telefon"] = phone_input

    next_msg = {
        "🇷🇺 Русский": "Опишите проблему:",
        "🇵🇱 Polski": "Opisz problem:",
        "🇬🇧 English": "Describe the issue:"
    }.get(lang)
    await update.message.reply_text(next_msg)
    return OPIS

async def get_opis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["opis"] = update.message.text
    slots = get_free_slots()
    if not slots:
        await update.message.reply_text("Нет доступных времён. Попробуйте позже.")
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(slot.strftime('%d.%m %H:%M'), callback_data=slot.isoformat())]
               for slot in [start for start, _ in slots[:10]]]

    lang = context.user_data.get("lang", "🇷🇺 Русский")
    text = {
        "🇷🇺 Русский": "Выберите удобное время:",
        "🇵🇱 Polski": "Wybierz dogodny termin:",
        "🇬🇧 English": "Choose a convenient time:"
    }.get(lang, "Выберите удобное время:")

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return SLOT_SELECT

# Установка кнопок командного меню Telegram
async def setup_bot_commands(app):
    # Команды для всех пользователей
    await app.bot.set_my_commands(
        [
            BotCommand("start", "🔹 Начало"),
            BotCommand("reset", "🔄 Сбросить режим ожидания"),
            BotCommand("help", "❓ Помощь"),
        ],
        scope=BotCommandScopeDefault()
    )

async def slot_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot_start = isoparse(query.data).astimezone(pytz.timezone("Europe/Warsaw"))
    slot_end = slot_start + timedelta(minutes=30)

    event = {
        'summary': f"Заявка от {context.user_data['telefon']}",
        'description': (
            f"{context.user_data['auto']} {context.user_data['year']}, "
            f"VIN: {context.user_data['vin']}\n"
            f"Проблема: {context.user_data['opis']}"
        ),
        'start': {'dateTime': slot_start.isoformat(), 'timeZone': 'Europe/Warsaw'},
        'end': {'dateTime': slot_end.isoformat(), 'timeZone': 'Europe/Warsaw'}
    }

        # Повторная проверка занятости
    check_body = {
        "timeMin": slot_start.isoformat(),
        "timeMax": slot_end.isoformat(),
        "timeZone": "Europe/Warsaw",
        "items": [{"id": CALENDAR_ID}]
    }

    try:
        busy = calendar_service.freebusy().query(body=check_body).execute()
        busy_times = busy['calendars'][CALENDAR_ID]['busy']
        overlapping = any(
            datetime.fromisoformat(b["start"]) < slot_end and datetime.fromisoformat(b["end"]) > slot_start
            for b in busy_times
        )

        if overlapping:
            lang = context.user_data.get("lang", "🇷🇺 Русский")
            msg = {
                "🇷🇺 Русский": "⚠️ Это время уже занято. Пожалуйста, выберите другое.",
                "🇵🇱 Polski": "⚠️ Ten termin jest już zajęty. Wybierz inny.",
                "🇬🇧 English": "⚠️ This time slot is already booked. Please choose another."
            }.get(lang, "⚠️ Это время уже занято. Пожалуйста, выберите другое.")
            await query.message.reply_text(msg)
            return SLOT_SELECT

        # Если всё свободно — создаём событие
        calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()

    except Exception as e:
        logging.error("❌ Ошибка при добавлении в календарь: %s", e)

    sheet.append_row([
        str(len(sheet.get_all_values())),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        context.user_data["auto"], context.user_data["year"], context.user_data["vin"],
        context.user_data["telefon"], context.user_data["opis"],
        slot_start.strftime('%Y-%m-%d %H:%M'), "Nowe"
    ])

    if ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=(
                f"🗓️ Новая заявка:\n"
                f"Марка: {context.user_data['auto']}\n"
                f"Год: {context.user_data['year']}\n"
                f"VIN: {context.user_data['vin']}\n"
                f"Телефон: {context.user_data['telefon']}\n"
                f"Проблема: {context.user_data['opis']}\n"
                f"Дата визита: {slot_start.strftime('%d.%m %H:%M')}"
            )
        )

    lang = context.user_data.get("lang", "🇷🇺 Русский")
    confirmation_message = {
        "🇷🇺 Русский": f"✅ Ваша запись подтверждена на {slot_start.strftime('%d.%m %H:%M')}. Спасибо!",
        "🇵🇱 Polski": f"✅ Twoja rezerwacja została potwierdzona na {slot_start.strftime('%d.%m %H:%M')}. Dziękujemy!",
        "🇬🇧 English": f"✅ Your appointment is confirmed for {slot_start.strftime('%d.%m %H:%M')}. Thank you!"
    }.get(lang)

    await query.edit_message_text(confirmation_message)
    return ConversationHandler.END

async def reload_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Эта команда доступна только администратору.")
        return

    global CONTACTS
    CONTACTS = load_contacts_from_sheet()
    await update.message.reply_text("✅ Контакты перезагружены.")

async def reload_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = (
        update.effective_user.id
        if update.effective_user
        else update.callback_query.from_user.id
    )
    if user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⛔ Эта команда доступна только администратору.")
        else:
            await update.callback_query.answer("⛔ Доступ запрещён", show_alert=True)
        return

    global PROMO_MESSAGES, CONTACTS
    PROMO_MESSAGES = load_promos_from_sheet()
    CONTACTS = load_contacts_from_sheet()

    if update.message:
        await update.message.reply_text("✅ Акции и контакты успешно перезагружены.")
    else:
        await update.callback_query.answer("✅ Данные обновлены", show_alert=True)

def get_free_slots():
    tz = pytz.timezone("Europe/Warsaw")
    today = datetime.now(tz).date()
    now = tz.localize(datetime.combine(today + timedelta(days=1), time(0, 0)))
    end_range = now + timedelta(days=14)
    work_start = time(8, 0)
    work_end = time(18, 0)
    slot_duration = timedelta(minutes=30)

    body = {
        "timeMin": now.isoformat(),
        "timeMax": end_range.isoformat(),
        "timeZone": "Europe/Warsaw",
        "items": [{"id": CALENDAR_ID}]
    }

    try:
        busy = calendar_service.freebusy().query(body=body).execute()
        busy_times = busy['calendars'][CALENDAR_ID]['busy']
        logging.info("📅 Занятых интервалов: %d", len(busy_times))
    except Exception as e:
        logging.error("❌ Ошибка при получении занятости календаря: %s", e)
        return []

    # Парсинг занятых интервалов с учетом таймзоны
    busy_intervals = []
    for b in busy_times:
        try:
            start = isoparse(b["start"])
            end = isoparse(b["end"])

            if start.tzinfo is None:
                start = tz.localize(start)
            else:
                start = start.astimezone(tz)

            if end.tzinfo is None:
                end = tz.localize(end)
            else:
                end = end.astimezone(tz)

            busy_intervals.append((start, end))
            logging.info("⛔ %s — %s", start, end)
        except Exception as e:
            logging.warning("⚠️ Ошибка при обработке занятости: %s", e)

    # Поиск свободных слотов
    free_slots = []
    current = now

    while current < end_range and len(free_slots) < 10:
        if current.weekday() < 5:  # Только рабочие дни
            slot_start = datetime.combine(current.date(), work_start, tz)
            slot_end = datetime.combine(current.date(), work_end, tz)

            while slot_start + slot_duration <= slot_end:
                is_busy = any(
                    max(slot_start, b_start) < min(slot_start + slot_duration, b_end)
                    for b_start, b_end in busy_intervals
                )
                if not is_busy:
                    free_slots.append((slot_start, slot_start + slot_duration))
                    logging.info("✅ Свободно: %s", slot_start)
                    if len(free_slots) >= 10:
                        break
                slot_start += slot_duration
        current += timedelta(days=1)

    return free_slots

# === Запуск ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

# Команда reset
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_question"] = False
    context.user_data["assistant_history"] = []
    await update.message.reply_text("🔄 Режим помощника сброшен. Вы можете выбрать другую функцию.")

# Команда help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Команды бота:\n"
        "/start — Начать\n"
        "/reset — Сбросить режим помощника\n"
        "/help — Помощь"
    )

async def send_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Эта команда доступна только администратору.")
        return

    try:
        promos = load_promos_from_sheet()

        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        rows = sub_sheet.get_all_values()[1:]

        lang_map = {
            "Русский": "🇷🇺 Русский",
            "Polski": "🇵🇱 Polski",
            "English": "🇬🇧 English"
        }

        for row in rows:
            if len(row) >= 2:
                user_id, raw_lang = row[0], row[1].strip()
                user_lang = lang_map.get(raw_lang, raw_lang)
                promo_text = promos.get(user_lang, promos.get("🇷🇺 Русский", "Привет 👋\n\n🔧 Весенние скидки!"))

                try:
                    await context.bot.send_message(chat_id=int(user_id), text=promo_text)
                except Exception as e:
                    logging.warning("⚠️ Не удалось отправить сообщение пользователю %s: %s", user_id, e)

        await update.message.reply_text("✅ Новость отправлена подписчикам.")

    except Exception as e:
        logging.error("❌ Ошибка при отправке новости: %s", e)
        await update.message.reply_text("⚠️ Ошибка при отправке новости.")

def get_promo_message(lang: str) -> str:
    try:
        promos = load_promos_from_sheet()
        return promos.get(lang, promos.get("🇷🇺 Русский", "Привет 👋\n\n🔧 Весенние скидки!"))
    except Exception as e:
        logging.warning("⚠️ Ошибка при получении промо: %s", e)
        return "Привет 👋\n\n🔧 Весенние скидки!"
    
# Загрузка акций из листа
def load_promos_from_sheet():
    try:
        promo_sheet = sheet_client.open(SHEET_NAME).worksheet("Акции")
        rows = promo_sheet.get_all_values()

        LANG_MAP = {
            "Русский": "🇷🇺 Русский",
            "Polski": "🇵🇱 Polski",
            "English": "🇬🇧 English"
        }

        promo_dict = {}
        for row in rows[1:]:
            if len(row) >= 2:
                lang_raw, text = row[0], row[1]
                lang = LANG_MAP.get(lang_raw.strip(), lang_raw.strip())
                promo_dict[lang] = text

        logging.info("📦 Загруженные промо: %s", promo_dict)
        return promo_dict

    except Exception as e:
        logging.error("❌ Ошибка при загрузке промо из таблицы: %s", e)
        return {}

def load_contacts_from_sheet():
    try:
        contact_sheet = sheet_client.open(SHEET_NAME).worksheet("Контакты")
        rows = contact_sheet.get_all_values()[1:]  # Пропускаем заголовок
        return {row[0].strip().upper(): row[1].strip() for row in rows if len(row) >= 2}
    except Exception as e:
        logging.error("❌ Ошибка при загрузке контактов: %s", e)
        return {}
    
PROMO_MESSAGES = load_promos_from_sheet()
CONTACTS = load_contacts_from_sheet()

# Обработчик кнопки "Назад"
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = context.user_data.get("lang", "🇷🇺 Русский")
    user_id = str(query.from_user.id)

    try:
        sub_sheet = sheet_client.open(SHEET_NAME).worksheet("Подписчики")
        ids = [row[0] for row in sub_sheet.get_all_values()[1:]]
        subscribed = user_id in ids
    except Exception as e:
        logging.warning("⚠️ Ошибка при проверке подписки: %s", e)
        subscribed = False

    subscribe_text = {
        "🇷🇺 Русский": "📬 Отписаться" if subscribed else "📬 Подписаться",
        "🇵🇱 Polski": "📬 Wypisz się" if subscribed else "📬 Subskrybuj",
        "🇬🇧 English": "📬 Unsubscribe" if subscribed else "📬 Subscribe"
    }.get(lang, "📬 Подписаться")

    promo = get_promo_message(lang)

    if lang == "🇵🇱 Polski":
        buttons = [
            [InlineKeyboardButton("📍 Adres", callback_data="address")],
            [InlineKeyboardButton("📝 Rejestracja", callback_data="zapis")],
            [InlineKeyboardButton("📞 Kontakt", callback_data="contacts")],
            [InlineKeyboardButton("🤖 Asystent diagnostyczny", callback_data="assistant")],
            [InlineKeyboardButton(subscribe_text, callback_data="subscribe")]
        ]
    elif lang == "🇬🇧 English":
        buttons = [
            [InlineKeyboardButton("📍 Address", callback_data="address")],
            [InlineKeyboardButton("📝 Appointment", callback_data="zapis")],
            [InlineKeyboardButton("📞 Contact", callback_data="contacts")],
            [InlineKeyboardButton("🤖 Assistant", callback_data="assistant")],
            [InlineKeyboardButton(subscribe_text, callback_data="subscribe")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📍 Адрес", callback_data="address")],
            [InlineKeyboardButton("📝 Запись", callback_data="zapis")],
            [InlineKeyboardButton("📞 Контакты", callback_data="contacts")],
            [InlineKeyboardButton("🤖 Помощник по неисправностям", callback_data="assistant")],
            [InlineKeyboardButton(subscribe_text, callback_data="subscribe")]
        ]

# 👑 Добавляем кнопку администратора
    if str(update.effective_user.id) == str(ADMIN_ID):
        admin_text = admin_button_text.get(lang, "♻️ Обновить данные")
        buttons.append([InlineKeyboardButton(admin_text, callback_data="reload_all")])
        buttons.append([InlineKeyboardButton("📢 Разослать новость", callback_data="send_news")])

    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=promo,
            reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logging.error("❌ Ошибка при обновлении меню: %s", e)

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_zapis, pattern="^zapis$")],
    states={
        AUTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_auto)],
        YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_year)],
        VIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vin)],
        TELEFON: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_telefon)],
        OPIS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_opis)],
        SLOT_SELECT: [CallbackQueryHandler(slot_selected, pattern=r"^\d{4}-\d{2}-\d{2}T")]
    },
    fallbacks=[CommandHandler("start", start)]
)

# === Запуск ===
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Хендлеры команд
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reset", reset_command))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("send_news", send_news))
app.add_handler(CommandHandler("reload_contacts", reload_contacts))
app.add_handler(CommandHandler("reload_all", reload_all))

# Остальные хендлеры
app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
app.add_handler(CallbackQueryHandler(change_language, pattern="^change_language$"))
app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))  
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    lambda update, context: handle_user_message(update, context, openai_client)
))

# Запуск и установка команд
async def main():
    await setup_bot_commands(app)
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
