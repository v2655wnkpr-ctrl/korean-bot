import calendar
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

TEACHER_LINK = "https://t.me/daru_usha"

# Новые премиум-эмодзи из твоего списка
E_LESSONS = "5372998306270035636" # 3. Книга
E_SETTINGS = "5373035595176098840" # 5. Лампочка
E_HW = "5373116439345511510" # 10. Список
E_HW_SETTINGS = "5370664330847075805" # 19. Галочка
E_CONTACT = "5377707548931543502" # 6. Самолетик
E_HELP = "5373107772101508671" # 17. Сердечко
E_ADD = "5373227270976584536" # 23. Карандаш
E_RESCHED = "5372908279460542562" # 13. Стрелка вправо
E_DELETE = "5262864719051504303" # 25. Крестик (взял из первого пака)
E_LIST = "5373116439345511510" # 10. Список
E_STATS = "5370941579575967992" # 4. Книга
E_PAY = "5372819657105360167" # 1. Мешок денег
E_SETPAID = "5370664330847075805" # 19. Галочка
E_CALENDAR = "5372998306270035636" # 3. Книга
E_FIND = "5373099637433450704" # 24. Вопрос
E_STUDENTS = "5373116439345511510" # 7. Чат


def main_menu_student():
    b = [
        [
            InlineKeyboardButton(text="Мои занятия", callback_data="menu:lessons", icon_custom_emoji_id=E_LESSONS),
            InlineKeyboardButton(text="Напоминания", callback_data="menu:settings", icon_custom_emoji_id=E_SETTINGS),
        ],
        [
            InlineKeyboardButton(text="📚 Домашки", callback_data="hw:list", icon_custom_emoji_id=E_HW),
            InlineKeyboardButton(text="⚙️ Настройки ДЗ", callback_data="hw_rem_settings", icon_custom_emoji_id=E_HW_SETTINGS),
        ],
        [
            InlineKeyboardButton(text="Связаться", url=TEACHER_LINK, icon_custom_emoji_id=E_CONTACT),
            InlineKeyboardButton(text="Помощь", callback_data="menu:help", icon_custom_emoji_id=E_HELP),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def main_menu_teacher():
    b = [
        [InlineKeyboardButton(text="Добавить занятие", callback_data="menu:add", icon_custom_emoji_id=E_ADD)],
        [
            InlineKeyboardButton(text="Перенести", callback_data="menu:reschedule", icon_custom_emoji_id=E_RESCHED),
            InlineKeyboardButton(text="Удалить", callback_data="menu:delete", icon_custom_emoji_id=E_DELETE),
        ],
        [
            InlineKeyboardButton(text="Все занятия", callback_data="menu:list", icon_custom_emoji_id=E_LIST),
            InlineKeyboardButton(text="Статистика", callback_data="menu:stats", icon_custom_emoji_id=E_STATS),
        ],
        [
            InlineKeyboardButton(text="Оплата", callback_data="menu:pay", icon_custom_emoji_id=E_PAY),
            InlineKeyboardButton(text="set_paid", callback_data="sp:open", icon_custom_emoji_id=E_SETPAID),
        ],
        [
            InlineKeyboardButton(text="Домашки", callback_data="menu:hw", icon_custom_emoji_id=E_HW),
            InlineKeyboardButton(text="Календарь", callback_data="menu:calendar", icon_custom_emoji_id=E_CALENDAR),
        ],
        [
            InlineKeyboardButton(text="Найти", callback_data="menu:find", icon_custom_emoji_id=E_FIND),
            InlineKeyboardButton(text="Ученики", callback_data="menu:students", icon_custom_emoji_id=E_STUDENTS),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)

# ... (Остальные функции keyboards.py остаются без изменений: timezone_offset_keyboard, back_to_main, hours_keyboard, pay_menu, tariffs_keyboard, card_keyboard, set_paid_students_keyboard, set_paid_amounts_keyboard, confirm_delete_student_keyboard, paid_button_keyboard, back_from_paid_keyboard, transfer_keyboard, transfer_cancel_keyboard, lessons_action_keyboard, confirm_delete_keyboard, hw_menu_teacher, hw_reminder_keyboard, calendar_keyboard) ...
# ПРОКРУТИ НИЖЕ, Я ДАМ ИХ ТОЛЬКО ЕСЛИ ОНИ ПОТЕРЯЛИСЬ

def hw_menu_teacher():
    b = [
        [InlineKeyboardButton(text="Создать ДЗ", callback_data="hw:create", icon_custom_emoji_id=E_ADD)],
        [InlineKeyboardButton(text="Все ДЗ", callback_data="hw:list_teacher", icon_custom_emoji_id=E_LIST)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)