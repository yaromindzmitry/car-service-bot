from telegram import Update
from telegram.ext import ContextTypes
import logging
from datetime import datetime

# Системные промпты по языкам
assistant_system_prompts = {
    "🇷🇺 Русский": (
        "Ты — профессиональный автомобильный диагност. \n"
        "Твоя задача — помочь пользователю определить неисправность машины по его описанию.\n"
        "Уточняй симптомы, задавай наводящие вопросы, исключай причины.\n"
        "Давай советы, какие элементы автомобиля проверить. Отвечай на русском языке."
    ),
    "🇵🇱 Polski": (
        "Jesteś profesjonalnym diagnostą samochodowym.\n"
        "Twoim zadaniem jest pomóc użytkownikowi zidentyfikować awarię auta na podstawie jego opisu.\n"
        "Zadawaj pytania uzupełniające, wykluczaj możliwe przyczyny, doradzaj co sprawdzić.\n"
        "Odpowiadaj po polsku."
    ),
    "🇬🇧 English": (
        "You are a professional car diagnostic assistant.\n"
        "Your goal is to help the user identify the car issue based on their description.\n"
        "Ask follow-up questions, rule out possible causes, suggest what to check.\n"
        "Respond in English."
    )
}

# Обработчик запуска помощника
async def handle_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_question"] = True
    context.user_data["assistant_history"] = []

    lang = context.user_data.get("lang", "🇷🇺 Русский")
    intro = {
        "🇷🇺 Русский": "✍️ Опишите вашу проблему с автомобилем. Я помогу диагностировать.",
        "🇵🇱 Polski": "✍️ Opisz problem z samochodem. Postaram się pomóc.",
        "🇬🇧 English": "✍️ Describe your car issue. I will help you diagnose it."
    }.get(lang, "✍️ Опишите вашу проблему.")

    await query.message.reply_text(intro)

# Обработчик сообщений от пользователя в режиме ассистента
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE, openai_client, sheet_client=None, sheet_name=None):
    if not context.user_data.get("awaiting_question"):
        return

    user_input = update.message.text.strip()

    if user_input.lower() in ["сброс", "reset", "новая проблема", "нова проблема"]:
        context.user_data["assistant_history"] = []
        await update.message.reply_text("🔁 История сброшена. Опишите новую проблему.")
        return

    lang = context.user_data.get("lang", "🇷🇺 Русский")
    system_prompt = assistant_system_prompts.get(lang, assistant_system_prompts["🇷🇺 Русский"])

    history = context.user_data.get("assistant_history", [])

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_input}
    ]

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})
        context.user_data["assistant_history"] = history

        await update.message.reply_text(reply, parse_mode="Markdown")

        # Логирование в Google Таблицу, если доступна
        if sheet_client and sheet_name:
            try:
                sheet = sheet_client.open(sheet_name).worksheet("Диалоги")
                sheet.append_row([
                    str(update.effective_user.id),
                    lang,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    user_input,
                    reply
                ])
            except Exception as log_err:
                logging.warning("⚠️ Не удалось записать диалог в таблицу: %s", log_err)

    except Exception as e:
        logging.error("OpenAI error: %s", e)
        await update.message.reply_text("⚠️ Ошибка при обращении к ИИ. Попробуйте позже.")