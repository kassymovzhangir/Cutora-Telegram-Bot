import os
import telebot
from telebot import types
from dotenv import load_dotenv

# Загружаем токен
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env")

TOKEN = TOKEN.strip()
bot = telebot.TeleBot(TOKEN)

bookings = {}
user_state = {}


# =========================
# ГЛАВНОЕ МЕНЮ
# =========================

def main_menu():
    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "✂️ Услуги и цены",
            callback_data="services"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 Выбрать мастера",
            callback_data="masters"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📅 Записаться",
            callback_data="book"
        )
    )

    return keyboard


# =========================
# МАСТЕРА
# =========================

def masters_menu():
    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 Арман",
            callback_data="master_arman"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 Айгерим",
            callback_data="master_aigerim"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "👤 Данияр",
            callback_data="master_daniyar"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Главное меню",
            callback_data="main"
        )
    )

    return keyboard


# =========================
# ВРЕМЯ
# =========================

def time_menu():
    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "16:00",
            callback_data="time_16"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "17:00",
            callback_data="time_17"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "18:30",
            callback_data="time_1830"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="back"
        )
    )

    return keyboard


# =========================
# ДЕЙСТВИЯ С ЗАПИСЬЮ
# =========================

def booking_actions():
    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Перенести запись",
            callback_data="reschedule"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "❌ Отменить запись",
            callback_data="cancel"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🏠 Главное меню",
            callback_data="main"
        )
    )

    return keyboard


# =========================
# /START
# =========================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    user_state[user_id] = "main"

    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в Cutora!\n\n"
        "Я помогу выбрать услугу, мастера и записаться "
        "в парикмахерскую.\n\n"
        "Выберите нужный раздел 👇",
        reply_markup=main_menu()
    )


# =========================
# ОБРАБОТКА КНОПОК
# =========================

@bot.callback_query_handler(func=lambda call: True)
def callback(call):

    bot.answer_callback_query(call.id)

    user_id = call.from_user.id
    chat_id = call.message.chat.id

    # Услуги
    if call.data == "services":

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="main"
            )
        )

        bot.send_message(
            chat_id,
            "✂️ Услуги и цены:\n\n"
            "Мужская стрижка — 7 000 ₸\n\n"
            "Женская стрижка — 9 000 ₸\n\n"
            "Классическая стрижка — 4 000 ₸",
            reply_markup=keyboard
        )

    # Выбор мастера
    elif call.data in ["masters", "book"]:

        user_state[user_id] = "choose_master"

        bot.send_message(
            chat_id,
            "Выберите мастера 👇",
            reply_markup=masters_menu()
        )

    # Арман
    elif call.data == "master_arman":

        if user_id not in bookings:
            bookings[user_id] = {}

        bookings[user_id]["master"] = "Арман"
        user_state[user_id] = "choose_time"

        bot.send_message(
            chat_id,
            "👤 Мастер: Арман\n"
            "На какое время вам удобно?",
            reply_markup=time_menu()
        )

    # Айгерим
    elif call.data == "master_aigerim":

        if user_id not in bookings:
            bookings[user_id] = {}

        bookings[user_id]["master"] = "Айгерим"
        user_state[user_id] = "choose_time"

        bot.send_message(
            chat_id,
            "👤 Мастер: Айгерим\n"
            "На какое время вам удобно?",
            reply_markup=time_menu()
        )

    # Данияр
    elif call.data == "master_daniyar":

        if user_id not in bookings:
            bookings[user_id] = {}

        bookings[user_id]["master"] = "Данияр"
        user_state[user_id] = "choose_time"

        bot.send_message(
            chat_id,
            "👤 Мастер: Данияр\n"
            "На какое время вам удобно?",
            reply_markup=time_menu()
        )

    # Время
    elif call.data in ["time_16", "time_17", "time_1830"]:

        times = {
            "time_16": "16:00",
            "time_17": "17:00",
            "time_1830": "18:30"
        }

        selected_time = times[call.data]

        if user_id not in bookings:
            bookings[user_id] = {}

        # Перенос
        if user_state.get(user_id) == "reschedule":

            bookings[user_id]["time"] = selected_time

            master = bookings[user_id].get(
                "master",
                "Не выбран"
            )

            bot.send_message(
                chat_id,
                "✅ Запись перенесена!\n\n"
                f"👤 Мастер: {master}\n"
                f"🕘 Новое время: {selected_time}",
                reply_markup=booking_actions()
            )

            user_state[user_id] = "booked"
            return

        # Новая запись
        bookings[user_id]["time"] = selected_time
        bookings[user_id]["service"] = "Стрижка"

        master = bookings[user_id].get(
            "master",
            "Не выбран"
        )

        bot.send_message(
            chat_id,
            "✅ Запись подтверждена!\n\n"
            f"👤 Мастер: {master}\n"
            f"🕘 Время: {selected_time}\n"
            "✂️ Стрижка\n\n"
            "Спасибо за запись в Cutora!",
            reply_markup=booking_actions()
        )

        user_state[user_id] = "booked"

    # Перенос
    elif call.data == "reschedule":

        if user_id not in bookings:

            bot.send_message(
                chat_id,
                "У вас нет активной записи.",
                reply_markup=main_menu()
            )

            return

        user_state[user_id] = "reschedule"

        bot.send_message(
            chat_id,
            "🔄 Перенос записи\n\n"
            "Выберите новое время 👇",
            reply_markup=time_menu()
        )

    # Отмена
    elif call.data == "cancel":

        if user_id in bookings:
            del bookings[user_id]

        user_state[user_id] = "main"

        bot.send_message(
            chat_id,
            "❌ Запись отменена\n\n"
            "Вернуться в главное меню? 👇",
            reply_markup=main_menu()
        )

    # Назад
    elif call.data == "back":

        if user_state.get(user_id) == "reschedule":

            user_state[user_id] = "booked"

            bot.send_message(
                chat_id,
                "Что хотите сделать с записью? 👇",
                reply_markup=booking_actions()
            )

        else:

            user_state[user_id] = "choose_master"

            bot.send_message(
                chat_id,
                "Выберите мастера 👇",
                reply_markup=masters_menu()
            )

    # Главное меню
    elif call.data == "main":

        user_state[user_id] = "main"

        bot.send_message(
            chat_id,
            "Выберите нужный раздел 👇",
            reply_markup=main_menu()
        )


print("Cutora Bot запущен!")
bot.infinity_polling(skip_pending=True)