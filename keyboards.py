from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

TEACHER_LINK = "https://t.me/v2655wnkpr"

E_LESSONS = "5343968081150486424"
E_SETTINGS = "5343705388065763490"
E_CONTACT = "5253967574038752898"
E_HELP = "5344015111042378193"
E_RESCHED = "5312111690240763536"
E_DELETE = "5341285689390542260"
E_LIST = "5343835843402411085"
E_STATS = "5343846413316925467"
E_SETPAID = "5343928112184831466"
E_FIND = "5343803218830829094"
E_STUDENTS = "5361658604766110429"


def main_menu_student():
    b = [
        [
            InlineKeyboardButton(text="Мои занятия", callback_data="menu:lessons", icon_custom_emoji_id=E_LESSONS),
            InlineKeyboardButton(text="Напоминания", callback_data="menu:settings", icon_custom_emoji_id=E_SETTINGS),
        ],
        [
            InlineKeyboardButton(text="📚 Домашки", callback_data="hw:list"),
        ],
        [
            InlineKeyboardButton(text="Связаться", url=TEACHER_LINK, icon_custom_emoji_id=E_CONTACT),
            InlineKeyboardButton(text="Помощь", callback_data="menu:help", icon_custom_emoji_id=E_HELP),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def main_menu_teacher():
    b = [
        [
            InlineKeyboardButton(text="➕ Добавить занятие", callback_data="menu:add"),
        ],
        [
            InlineKeyboardButton(text="Перенести", callback_data="menu:reschedule", icon_custom_emoji_id=E_RESCHED),
            InlineKeyboardButton(text="Удалить", callback_data="menu:delete", icon_custom_emoji_id=E_DELETE),
        ],
        [
            InlineKeyboardButton(text="Все занятия", callback_data="menu:list", icon_custom_emoji_id=E_LIST),
            InlineKeyboardButton(text="Статистика", callback_data="menu:stats", icon_custom_emoji_id=E_STATS),
        ],
        [
            InlineKeyboardButton(text="💰 Оплата", callback_data="menu:pay"),
            InlineKeyboardButton(text="set_paid", callback_data="sp:open", icon_custom_emoji_id=E_SETPAID),
        ],
        [
            InlineKeyboardButton(text="📚 Домашки", callback_data="menu:hw"),
        ],
        [
            InlineKeyboardButton(text="Найти", callback_data="menu:find", icon_custom_emoji_id=E_FIND),
            InlineKeyboardButton(text="Ученики", callback_data="menu:students", icon_custom_emoji_id=E_STUDENTS),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def back_to_main(cb: str = "menu:main"):
    b = [[InlineKeyboardButton(text="⬅️ Назад", callback_data=cb)]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hours_keyboard():
    b = [
        [
            InlineKeyboardButton(text="1 час", callback_data="h:1"),
            InlineKeyboardButton(text="3 часа", callback_data="h:3"),
        ],
        [
            InlineKeyboardButton(text="1 день", callback_data="h:24"),
            InlineKeyboardButton(text="2 дня", callback_data="h:48"),
        ],
        [
            InlineKeyboardButton(text="Неделя", callback_data="h:168"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def pay_menu():
    b = [
        [InlineKeyboardButton(text="💳 После урока", callback_data="pay:after")],
        [InlineKeyboardButton(text="⏰ Абонемент", callback_data="pay:end")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def tariffs_keyboard():
    b = [
        [InlineKeyboardButton(text="Индивид. 4 зан.", callback_data="tar:ind_4")],
        [InlineKeyboardButton(text="Индивид. 8 зан.", callback_data="tar:ind_8")],
        [InlineKeyboardButton(text="Группа 4 зан.", callback_data="tar:grp_4")],
        [InlineKeyboardButton(text="Группа 8 зан.", callback_data="tar:grp_8")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def card_keyboard(student_id: int):
    b = [
        [
            InlineKeyboardButton(text="➕ Занятие", callback_data=f"act:add:{student_id}"),
            InlineKeyboardButton(text="💰 Оплата", callback_data=f"act:pay:{student_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"stdel:ask:{student_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def set_paid_students_keyboard(students):
    b = []
    for s in students:
        name = s.full_name
        if len(name) > 28:
            name = name[:28] + "..."
        b.append([InlineKeyboardButton(text=name, callback_data=f"sp:{s.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=b)


def set_paid_amounts_keyboard(sid: int, current: int = 0):
    b = [
        [
            InlineKeyboardButton(text="4 зан.", callback_data=f"spa:{sid}:4"),
            InlineKeyboardButton(text="8 зан.", callback_data=f"spa:{sid}:8"),
        ],
        [
            InlineKeyboardButton(text="12 зан.", callback_data=f"spa:{sid}:12"),
            InlineKeyboardButton(text="16 зан.", callback_data=f"spa:{sid}:16"),
        ],
        [
            InlineKeyboardButton(text="➖ -1", callback_data=f"spa:{sid}:{current - 1}"),
            InlineKeyboardButton(text=f"Сейчас: {current}", callback_data="ignore"),
            InlineKeyboardButton(text="➕ +1", callback_data=f"spa:{sid}:{current + 1}"),
        ],
        [
            InlineKeyboardButton(text="❌ Обнулить", callback_data=f"spa:{sid}:0"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="sp:open"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def confirm_delete_student_keyboard(sid: int):
    b = [[
        InlineKeyboardButton(text="🗑 Да", callback_data=f"stdel:{sid}"),
        InlineKeyboardButton(text="❌ Нет", callback_data="menu:main"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def paid_button_keyboard():
    b = [
        [InlineKeyboardButton(text="📋 Посмотреть абонементы", callback_data="show:tariffs")],
        [InlineKeyboardButton(text="💳 Я оплатил(а)", callback_data="paid:click")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def back_from_paid_keyboard():
    b = [[InlineKeyboardButton(text="⬅️ Отмена", callback_data="paid:back")]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def transfer_keyboard():
    b = [[InlineKeyboardButton(text="Перенести", callback_data="transfer:click", icon_custom_emoji_id=E_RESCHED)]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def transfer_cancel_keyboard():
    b = [[InlineKeyboardButton(text="❌ Отмена", callback_data="transfer:cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def lessons_action_keyboard(lessons, action):
    b = []
    for les in lessons[:15]:
        dt = les.datetime_start
        txt = dt.strftime("%d.%m %H:%M")
        txt += f" — {les.title}"
        b.append([InlineKeyboardButton(text=txt, callback_data=f"{action}:{les.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=b)


def confirm_delete_keyboard(lid: int):
    b = [
        [
            InlineKeyboardButton(text="Удалить", callback_data=f"confirm_del:{lid}", icon_custom_emoji_id=E_DELETE),
            InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hw_menu_teacher():
    b = [
        [InlineKeyboardButton(text="➕ Создать ДЗ", callback_data="hw:create")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hw_reminder_keyboard(days: int, enabled: bool):
    btn_text = "❌ Выключить" if enabled else "✅ Включить"
    b = [
        [InlineKeyboardButton(text=f"За {days} дн.", callback_data=f"hwrem:{days}")],
        [InlineKeyboardButton(text=btn_text, callback_data="hwrem:toggle")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)