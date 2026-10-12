
import os
import logging
import telebot
from telebot import types
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not all((TOKEN, SUPABASE_URL, SUPABASE_KEY)):
    raise ValueError("Проверьте BOT_TOKEN, SUPABASE_URL и SUPABASE_KEY в .env")

logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MASTERS = {
    "arman": ("Арман", ["17:00", "18:30", "16:00"]),
    "aigerim": ("Айгерим", ["19:00", "17:30", "18:00"]),
    "daniyar": ("Данияр", ["19:00", "19:30", "20:00"]),
}


def keyboard(*buttons):
    kb = types.InlineKeyboardMarkup()
    for title, action in buttons:
        kb.add(types.InlineKeyboardButton(title, callback_data=action))
    return kb


def main_menu():
    return keyboard(
        ("✂️ Услуги и цены", "services"),
        ("👤 Выбрать мастера", "masters"),
        ("📅 Записаться", "booking"),
        ("📋 Мои записи", "my_booking"),
    )


def masters_menu():
    return keyboard(
        ("👤 Арман", "master:arman"),
        ("👤 Айгерим", "master:aigerim"),
        ("👤 Данияр", "master:daniyar"),
        ("⬅️ Главное меню", "main"),
    )


def time_menu(master_key, mode="new", current_time=None):
    name, slots = MASTERS[master_key]
    buttons = []

    for time in slots:
        if mode == "move" and time == current_time:
            continue

        # Каждая кнопка содержит мастера и время.
        buttons.append((time, f"slot:{mode}:{master_key}:{time}"))

    back = "actions" if mode == "move" else "masters"
    buttons.append(("⬅️ Назад", back))
    return keyboard(*buttons)


def actions_menu():
    return keyboard(
        ("🔄 Перенести запись", "reschedule"),
        ("❌ Отменить запись", "cancel"),
        ("🏠 Главное меню", "main"),
    )


def booking_details(record):
    return (
        f"👤 Мастер: {record['master']}\n"
        f"🕒 Время: {record['booking_time']}\n"
        f"✂️ Услуга: {record['service']}"
    )


def get_booking(user_id):
    result = (
        supabase.table("bookings")
        .select("telegram_id,master,service,booking_time")
        .eq("telegram_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def save_booking(user_id, master, time, service="Стрижка"):
    supabase.table("bookings").upsert(
        {
            "telegram_id": user_id,
            "master": master,
            "service": service,
            "booking_time": time,
        },
        on_conflict="telegram_id",
    ).execute()


def delete_booking(user_id):
    supabase.table("bookings").delete().eq(
        "telegram_id", user_id
    ).execute()


def show_booking(chat_id, user_id):
    record = get_booking(user_id)

    if record:
        bot.send_message(
            chat_id,
            "У вас уже есть активная запись:\n\n"
            + booking_details(record)
            + "\n\nЧто хотите сделать с записью? 👇",
            reply_markup=actions_menu(),
        )
    else:
        bot.send_message(
            chat_id,
            "У вас нет активной записи.",
            reply_markup=main_menu(),
        )


@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "👋 Добро пожаловать в Cutora!\n\n"
        "Я помогу выбрать услугу, мастера и записаться "
        "в парикмахерскую.\n\n"
        "Выберите нужный раздел 👇",
        reply_markup=main_menu(),
    )


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.answer_callback_query(call.id)

    action = call.data or ""
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    try:
        if action == "main":
            bot.send_message(
                chat_id,
                "Выберите нужный раздел 👇",
                reply_markup=main_menu(),
            )

        elif action == "services":
            bot.send_message(
                chat_id,
                "✂️ Услуги и цены:\n\n"
                "Мужская стрижка — 7 000 ₸\n"
                "Женская стрижка — 9 000 ₸\n"
                "Классическая стрижка — 4 000 ₸",
                reply_markup=keyboard(
                    ("📅 Записаться", "booking"),
                    ("⬅️ Главное меню", "main"),
                ),
            )

        elif action in ("masters", "booking"):
            bot.send_message(
                chat_id,
                "👤 Выберите мастера 👇",
                reply_markup=masters_menu(),
            )

        elif action.startswith("master:"):
            master_key = action.split(":", 1)[1]

            if master_key not in MASTERS:
                bot.send_message(
                    chat_id,
                    "Мастер не найден.",
                    reply_markup=masters_menu(),
                )
                return

            name, slots = MASTERS[master_key]

            bot.send_message(
                chat_id,
                f"👤 Мастер: {name}\n"
                "На какое время вам удобно?",
                reply_markup=time_menu(master_key),
            )

        elif action.startswith("slot:"):
            parts = action.split(":")

            if len(parts) != 5:
                bot.send_message(
                    chat_id,
                    "Выберите мастера заново.",
                    reply_markup=masters_menu(),
                )
                return

            _, mode, master_key, hour, minute = parts
            selected_time = f"{hour}:{minute}"

            if mode not in ("new", "move") or master_key not in MASTERS:
                bot.send_message(
                    chat_id,
                    "Выберите мастера заново.",
                    reply_markup=masters_menu(),
                )
                return

            master, available_times = MASTERS[master_key]

            if selected_time not in available_times:
                bot.send_message(
                    chat_id,
                    "Выберите время из списка.",
                    reply_markup=time_menu(master_key, mode),
                )
                return

            existing = get_booking(user_id)

            if mode == "move":
                if not existing:
                    bot.send_message(
                        chat_id,
                        "У вас нет активной записи.",
                        reply_markup=main_menu(),
                    )
                    return

                if existing["master"] != master:
                    bot.send_message(
                        chat_id,
                        "Для переноса выберите время своего мастера.",
                        reply_markup=actions_menu(),
                    )
                    return

                save_booking(
                    user_id,
                    master,
                    selected_time,
                    existing["service"],
                )

                bot.send_message(
                    chat_id,
                    "✅ Запись перенесена!\n"
                    f"👤 Мастер: {master}\n"
                    f"🕒 Новое время: {selected_time}\n\n"
                    "Выберите дальнейшее действие 👇",
                    reply_markup=keyboard(
                        ("🏠 Главное меню", "main")
                    ),
                )

            else:
                save_booking(user_id, master, selected_time)

                bot.send_message(
                    chat_id,
                    "✅ Запись подтверждена!\n"
                    f"👤 Мастер: {master}\n"
                    f"🕒 Время: {selected_time}\n"
                    "✂️ Стрижка\n"
                    "Спасибо за запись в Cutora!\n\n"
                    "Что хотите сделать с записью? 👇",
                    reply_markup=actions_menu(),
                )

        elif action in ("my_booking", "actions"):
            show_booking(chat_id, user_id)

        elif action == "reschedule":
            existing = get_booking(user_id)

            if not existing:
                bot.send_message(
                    chat_id,
                    "У вас нет активной записи.",
                    reply_markup=main_menu(),
                )
                return

            master_key = next(
                (
                    key
                    for key, (name, slots) in MASTERS.items()
                    if name == existing["master"]
                ),
                None,
            )

            if master_key is None:
                bot.send_message(
                    chat_id,
                    "Мастер не найден.",
                    reply_markup=main_menu(),
                )
                return

            bot.send_message(
                chat_id,
                f"🔄 Перенос записи {existing['master']} "
                f"{existing['booking_time']}\n\n"
                "Выберите новое время для записи 👇",
                reply_markup=time_menu(
                    master_key,
                    mode="move",
                    current_time=existing["booking_time"],
                ),
            )

        elif action == "cancel":
            existing = get_booking(user_id)

            if existing:
                delete_booking(user_id)
                bot.send_message(
                    chat_id,
                    "✅ Запись отменена.\n\n"
                    "Вернуться в главное меню? 👇",
                    reply_markup=keyboard(
                        ("🏠 Главное меню", "main")
                    ),
                )
            else:
                bot.send_message(
                    chat_id,
                    "У вас нет активной записи.",
                    reply_markup=main_menu(),
                )

        elif action.startswith("time_") or action.startswith("master_"):
            bot.send_message(
                chat_id,
                "Это кнопка из старой версии бота.\n"
                "Выберите мастера заново 👇",
                reply_markup=masters_menu(),
            )

        else:
            bot.send_message(
                chat_id,
                "Выберите действие из меню.",
                reply_markup=main_menu(),
            )

    except Exception:
        logging.exception("Ошибка при обработке кнопки")
        bot.send_message(
            chat_id,
            "⚠️ Не удалось выполнить действие. "
            "Проверьте подключение к Supabase.",
            reply_markup=main_menu(),
        )


@bot.message_handler(func=lambda message: True)
def unknown(message):
    bot.send_message(
        message.chat.id,
        "Пожалуйста, используйте кнопки 👇",
        reply_markup=main_menu(),
    )

if __name__ == "__main__":
    print("Cutora Bot запущен!")
    bot.infinity_polling(skip_pending=True)
    
