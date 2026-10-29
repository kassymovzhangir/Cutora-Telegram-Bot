import os
import re
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import telebot
from telebot import types
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
TOKEN = os.getenv('BOT_TOKEN', '').strip()
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
TZ = ZoneInfo('Asia/Almaty')

if not all((TOKEN, SUPABASE_URL, SUPABASE_KEY)):
    raise ValueError('Нужны BOT_TOKEN, SUPABASE_URL и SUPABASE_KEY в Railway Variables или .env')

logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Данные старой таблицы bookings не удаляем; ниже сохранён просмотр/отмена старой записи.
# Новые реальные записи создаются только в cutora_appointments.
DEFAULT_TIMES = ['17:00', '18:00', '19:00']


def keyboard(*buttons):
    kb = types.InlineKeyboardMarkup()
    for title, action in buttons:
        kb.add(types.InlineKeyboardButton(title, callback_data=action))
    return kb


def main_menu():
    return keyboard(
        ('✂️ Услуги и цены', 'services'),
        ('👤 Выбрать мастера', 'masters'),
        ('📅 Записаться', 'booking'),
        ('📋 Мои записи', 'my_booking'),
        ('✂️ Зарегистрироваться как мастер', 'register_master'),
    )


def actions_menu():
    return keyboard(
        ('🔄 Перенести запись', 'reschedule'),
        ('❌ Отменить запись', 'cancel'),
        ('🏠 Главное меню', 'main'),
    )


def back_menu():
    return keyboard(('⬅️ Главное меню', 'main'))


def get_master(master_id, approved=True):
    q = supabase.table('cutora_masters').select('*').eq('id', master_id)
    if approved:
        q = q.eq('status', 'approved')
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


def approved_masters():
    return (supabase.table('cutora_masters')
            .select('id,full_name,specialization,salon_name')
            .eq('status', 'approved').order('id').execute().data or [])


def masters_menu():
    rows = approved_masters()
    if not rows:
        return back_menu()
    buttons = [('👤 ' + str(m['full_name']), f"master:{m['id']}") for m in rows]
    buttons.append(('⬅️ Главное меню', 'main'))
    return keyboard(*buttons)


def parse_times(master):
    raw = master.get('available_times')
    values = raw.split(',') if isinstance(raw, str) and raw.strip() else DEFAULT_TIMES
    result = []
    for item in values:
        item = item.strip()
        try:
            datetime.strptime(item, '%H:%M')
            if item not in result:
                result.append(item)
        except ValueError:
            pass
    return sorted(result)


def get_legacy_booking(user_id):
    rows = (supabase.table('bookings').select('telegram_id,master,service,booking_time')
            .eq('telegram_id', user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def current_appointment(user_id):
    # Записи в прошлом не считаем активными.
    rows = (supabase.table('cutora_appointments').select('*')
            .eq('client_telegram_id', user_id).eq('status', 'confirmed')
            .gte('appointment_at', datetime.now(TZ).isoformat())
            .order('appointment_at').limit(1).execute().data or [])
    return rows[0] if rows else None


def format_dt(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.astimezone(TZ).strftime('%d.%m.%Y в %H:%M')


def master_name(master_id):
    m = get_master(master_id, approved=False)
    return m['full_name'] if m else 'Мастер'


def show_booking(chat_id, user_id):
    booking = current_appointment(user_id)
    if booking:
        bot.send_message(
            chat_id,
            'У вас есть активная запись:\n\n'
            f"👤 Мастер: {master_name(booking['master_id'])}\n"
            f"🕒 Дата и время: {format_dt(booking['appointment_at'])}\n"
            f"✂️ Услуга: {booking['service']}\n\n"
            'Что хотите сделать с записью? 👇',
            reply_markup=actions_menu(),
        )
        return

    legacy = get_legacy_booking(user_id)
    if legacy:
        bot.send_message(
            chat_id,
            'Старая запись (без даты):\n\n'
            f"👤 Мастер: {legacy['master']}\n"
            f"🕒 Время: {legacy['booking_time']}\n"
            f"✂️ Услуга: {legacy['service']}\n\n"
            'Эта запись относится к прежней версии бота. Её можно отменить; '
            'для настоящей записи выберите мастера заново.',
            reply_markup=actions_menu(),
        )
    else:
        bot.send_message(chat_id, 'У вас нет активной записи.', reply_markup=main_menu())


def registration_command(message):
    """Allow /start and /cancel even when a registration step is pending."""
    command = (message.text or '').split(maxsplit=1)[0].split('@')[0].lower() if message.text else ''
    if command not in ('/start', '/cancel'):
        return False
    bot.clear_step_handler_by_chat_id(message.chat.id)
    if command == '/start':
        send_welcome(message.chat.id)
    else:
        bot.send_message(message.chat.id, 'Регистрация отменена. Выберите нужный раздел 👇',
                         reply_markup=main_menu())
    return True


def begin_registration(chat_id, user_id):
    existing = (supabase.table('cutora_masters').select('id,status')
                .eq('telegram_id', user_id).limit(1).execute().data or [])
    if existing:
        status = existing[0]['status']
        text = {'pending': '⏳ Ваша заявка уже ожидает подтверждения.',
                'approved': '✅ Вы уже зарегистрированы как мастер.',
                'rejected': '❌ Ваша заявка отклонена. Обратитесь к администратору.'}.get(status, 'Заявка уже есть.')
        bot.send_message(chat_id, text, reply_markup=main_menu())
        return
    prompt = bot.send_message(chat_id, '✂️ Регистрация мастера Cutora\n\nВведите имя и фамилию:')
    bot.register_next_step_handler(prompt, register_master_name, user_id)


def register_master_name(message, user_id):
    if registration_command(message):
        return
    if message.from_user.id != user_id:
        return
    name = (message.text or '').strip()
    if not 2 <= len(name) <= 100 or name.startswith('/'):
        prompt = bot.send_message(message.chat.id, 'Введите корректное имя и фамилию (2–100 символов):')
        bot.register_next_step_handler(prompt, register_master_name, user_id)
        return
    prompt = bot.send_message(message.chat.id, 'Введите номер телефона (например, +77011234567):')
    bot.register_next_step_handler(prompt, register_master_phone, user_id, name)


def register_master_phone(message, user_id, name):
    if registration_command(message):
        return
    if message.from_user.id != user_id:
        return
    phone = re.sub(r'[\s()\-]', '', (message.text or '').strip())
    if not re.fullmatch(r'\+?\d{10,15}', phone):
        prompt = bot.send_message(message.chat.id, 'Введите телефон из 10–15 цифр:')
        bot.register_next_step_handler(prompt, register_master_phone, user_id, name)
        return
    prompt = bot.send_message(message.chat.id, 'Укажите специализацию (например: мужские стрижки):')
    bot.register_next_step_handler(prompt, register_master_specialization, user_id, name, phone)


def register_master_specialization(message, user_id, name, phone):
    if registration_command(message):
        return
    if message.from_user.id != user_id:
        return
    specialization = (message.text or '').strip()
    if not 2 <= len(specialization) <= 150 or specialization.startswith('/'):
        prompt = bot.send_message(message.chat.id, 'Введите специализацию (2–150 символов):')
        bot.register_next_step_handler(prompt, register_master_specialization, user_id, name, phone)
        return
    prompt = bot.send_message(message.chat.id, 'Укажите свободные часы через запятую, например: 17:00,18:30,19:00')
    bot.register_next_step_handler(prompt, register_master_times, user_id, name, phone, specialization)


def register_master_times(message, user_id, name, phone, specialization):
    if registration_command(message):
        return
    if message.from_user.id != user_id:
        return
    raw = (message.text or '').strip()
    times = []
    try:
        for part in raw.split(','):
            part = part.strip()
            datetime.strptime(part, '%H:%M')
            if part not in times:
                times.append(part)
        if not 1 <= len(times) <= 20:
            raise ValueError()
    except ValueError:
        prompt = bot.send_message(message.chat.id, 'Неверный формат. Пример: 17:00,18:30,19:00')
        bot.register_next_step_handler(prompt, register_master_times, user_id, name, phone, specialization)
        return
    try:
        # Проверка и INSERT, а не UPSERT: повторная заявка не меняет approved на pending.
        old = (supabase.table('cutora_masters').select('id,status')
               .eq('telegram_id', user_id).limit(1).execute().data or [])
        if old:
            bot.send_message(message.chat.id, 'Ваша заявка уже существует.', reply_markup=main_menu())
            return
        supabase.table('cutora_masters').insert({
            'telegram_id': user_id,
            'full_name': name,
            'phone': phone,
            'specialization': specialization,
            'available_times': ','.join(times),
            'status': 'pending',
        }).execute()
        bot.send_message(message.chat.id,
                         '✅ Заявка сохранена! После подтверждения администратором '
                         'вы появитесь в списке мастеров.', reply_markup=main_menu())
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id,
                                 f'Новая заявка мастера: {name}. Откройте Supabase → cutora_masters для проверки.')
            except Exception:
                logging.exception('Не удалось уведомить администратора')
    except Exception:
        logging.exception('Ошибка регистрации мастера')
        bot.send_message(message.chat.id, '❌ Не удалось сохранить заявку. Проверьте таблицу и попробуйте позже.')


def dates_menu(master_id):
    kb = types.InlineKeyboardMarkup()
    today = datetime.now(TZ).date()
    for offset in range(14):
        d = today + timedelta(days=offset)
        kb.add(types.InlineKeyboardButton(d.strftime('%d.%m.%Y'), callback_data=f'date:{master_id}:{d.isoformat()}'))
    kb.add(types.InlineKeyboardButton('⬅️ К мастерам', callback_data='masters'))
    return kb


def slots_menu(master_id, day):
    master = get_master(master_id)
    if not master:
        return back_menu()
    times = parse_times(master)
    start = datetime.fromisoformat(day).date()
    busy_rows = (supabase.table('cutora_appointments').select('appointment_at')
                 .eq('master_id', master_id).eq('status', 'confirmed')
                 .gte('appointment_at', datetime.combine(start, time.min, TZ).isoformat())
                 .lt('appointment_at', datetime.combine(start + timedelta(days=1), time.min, TZ).isoformat())
                 .execute().data or [])
    busy = {format_dt(row['appointment_at'])[-5:] for row in busy_rows}
    buttons = []
    for slot in times:
        if slot in busy:
            continue
        dt = datetime.fromisoformat(f'{day}T{slot}:00').replace(tzinfo=TZ)
        if dt <= datetime.now(TZ):
            continue
        buttons.append((f'🕒 {slot}', f'book:{master_id}:{day}:{slot.replace(":", "")}'))
    buttons.append(('⬅️ Выбрать дату', f'master:{master_id}'))
    return keyboard(*buttons), bool(len(buttons) > 1)


def notify_master(master_id, text):
    master = get_master(master_id, approved=False)
    if master:
        try:
            bot.send_message(master['telegram_id'], text)
        except Exception:
            logging.exception('Не удалось уведомить мастера')


def send_welcome(chat_id):
    bot.send_message(chat_id,
                     '👋 Добро пожаловать в Cutora!\n\n'
                     'Я помогу выбрать услугу, мастера и записаться в парикмахерскую.\n\n'
                     'Выберите нужный раздел 👇', reply_markup=main_menu())


@bot.message_handler(commands=['start'])
def start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    send_welcome(message.chat.id)


@bot.message_handler(commands=['cancel'])
def cancel_registration(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.send_message(message.chat.id, 'Регистрация отменена. Выберите нужный раздел 👇',
                     reply_markup=main_menu())


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.answer_callback_query(call.id)
    action = call.data or ''
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    try:
        if action in ('main', 'register_master'):
            bot.clear_step_handler_by_chat_id(chat_id)
        if action == 'main':
            bot.send_message(chat_id, 'Выберите нужный раздел 👇', reply_markup=main_menu())
        elif action == 'services':
            bot.send_message(chat_id,
                             '✂️ Услуги и цены:\n\nМужская стрижка — 7 000 ₸\n'
                             'Женская стрижка — 9 000 ₸\nКлассическая стрижка — 4 000 ₸',
                             reply_markup=keyboard(('📅 Записаться', 'booking'), ('⬅️ Главное меню', 'main')))
        elif action == 'register_master':
            begin_registration(chat_id, user_id)
        elif action in ('masters', 'booking'):
            rows = approved_masters()
            bot.send_message(chat_id,
                             '👤 Выберите мастера 👇' if rows else
                             'Пока нет подтверждённых мастеров. Регистрация доступна через главное меню.',
                             reply_markup=masters_menu())
        elif action.startswith('master:'):
            master_id = int(action.split(':', 1)[1])
            master = get_master(master_id)
            if not master:
                bot.send_message(chat_id, 'Мастер не найден или ещё не подтверждён.', reply_markup=masters_menu())
                return
            bot.send_message(chat_id,
                             f"👤 Мастер: {master['full_name']}\n"
                             f"✂️ Специализация: {master.get('specialization') or 'Стрижка'}\n\n"
                             '📅 Выберите дату:', reply_markup=dates_menu(master_id))
        elif action.startswith('date:'):
            _, master_str, day = action.split(':', 2)
            master_id = int(master_str)
            d = datetime.strptime(day, '%Y-%m-%d').date()
            if not 0 <= (d - datetime.now(TZ).date()).days < 14 or not get_master(master_id):
                bot.send_message(chat_id, 'Выберите дату и мастера заново.', reply_markup=masters_menu())
                return
            kb, available = slots_menu(master_id, day)
            bot.send_message(chat_id,
                             f'📅 {d.strftime("%d.%m.%Y")}\n'
                             + ('Выберите свободное время:' if available else 'Свободного времени нет. Выберите другую дату.'),
                             reply_markup=kb)
        elif action.startswith('book:'):
            _, master_str, day, hhmm = action.split(':', 3)
            master_id = int(master_str)
            if not re.fullmatch(r'\d{4}', hhmm):
                raise ValueError('Неверное время')
            slot = hhmm[:2] + ':' + hhmm[2:]
            target_day = datetime.strptime(day, '%Y-%m-%d').date()
            dt = datetime.fromisoformat(f'{day}T{slot}:00').replace(tzinfo=TZ)
            master = get_master(master_id)
            if (not master or slot not in parse_times(master) or
                    not 0 <= (target_day - datetime.now(TZ).date()).days < 14 or
                    dt <= datetime.now(TZ)):
                bot.send_message(chat_id, 'Это время недоступно. Выберите заново.', reply_markup=masters_menu())
                return
            if current_appointment(user_id) or get_legacy_booking(user_id):
                bot.send_message(chat_id, 'У вас уже есть запись. Сначала откройте «Мои записи».', reply_markup=main_menu())
                return
            try:
                supabase.table('cutora_appointments').insert({
                    'master_id': master_id,
                    'client_telegram_id': user_id,
                    'service': 'Стрижка',
                    'appointment_at': dt.isoformat(),
                    'status': 'confirmed',
                }).execute()
            except Exception:
                logging.exception('Ошибка бронирования (возможно, время уже занято)')
                bot.send_message(chat_id, '⚠️ Время уже занято или запись не сохранилась. Выберите другое время.',
                                 reply_markup=dates_menu(master_id))
                return
            bot.send_message(chat_id,
                             f"✅ Запись подтверждена!\n👤 Мастер: {master['full_name']}\n"
                             f"📅 Дата: {target_day.strftime('%d.%m.%Y')}\n🕒 Время: {slot}\n"
                             '✂️ Услуга: Стрижка\n\nСпасибо за запись в Cutora!', reply_markup=actions_menu())
            notify_master(master_id, f'📅 Новая запись!\nДата: {target_day.strftime("%d.%m.%Y")}\nВремя: {slot}\nУслуга: Стрижка')
        elif action in ('my_booking', 'actions'):
            show_booking(chat_id, user_id)
        elif action == 'cancel':
            booking = current_appointment(user_id)
            if booking:
                (supabase.table('cutora_appointments').update({'status': 'cancelled'})
                 .eq('id', booking['id']).eq('client_telegram_id', user_id).eq('status', 'confirmed').execute())
                bot.send_message(chat_id, '✅ Запись отменена.', reply_markup=main_menu())
                notify_master(booking['master_id'], f"❌ Клиент отменил запись на {format_dt(booking['appointment_at'])}.")
            elif get_legacy_booking(user_id):
                supabase.table('bookings').delete().eq('telegram_id', user_id).execute()
                bot.send_message(chat_id, '✅ Старая запись отменена.', reply_markup=main_menu())
            else:
                bot.send_message(chat_id, 'У вас нет активной записи.', reply_markup=main_menu())
        elif action == 'reschedule':
            booking = current_appointment(user_id)
            if booking:
                bot.send_message(chat_id, 'Для переноса отмените текущую запись и выберите новое время. '
                                 'Так мы не потеряем занятый слот.', reply_markup=actions_menu())
            elif get_legacy_booking(user_id):
                bot.send_message(chat_id, 'Для старой записи сначала нажмите «Отменить запись», '
                                 'затем запишитесь на конкретную дату.', reply_markup=actions_menu())
            else:
                bot.send_message(chat_id, 'У вас нет активной записи.', reply_markup=main_menu())
        else:
            bot.send_message(chat_id, 'Выберите действие из меню.', reply_markup=main_menu())
    except Exception:
        logging.exception('Ошибка при обработке кнопки')
        bot.send_message(chat_id, '⚠️ Не удалось выполнить действие. Попробуйте ещё раз.', reply_markup=main_menu())


@bot.message_handler(func=lambda message: True)
def unknown(message):
    bot.send_message(message.chat.id, 'Пожалуйста, используйте кнопки 👇', reply_markup=main_menu())


if __name__ == '__main__':
    print('Cutora Bot запущен!')
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
