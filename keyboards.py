import calendar
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

TEACHER_LINK = "https://t.me/daru_usha"

E_LESSONS = "5372998306270035636"
E_SETTINGS = "5373035595176098840"
E_HW = "5373116439345511510"
E_HW_SETTINGS = "5370664330847075805"
E_CONTACT = "5377707548931543502"
E_HELP = "5373107772101508671"
E_ADD = "5373227270976584536"
E_RESCHED = "5372908279460542562"
E_DELETE = "5262864719051504303"
E_LIST = "5373116439345511510"
E_STATS = "5370941579575967992"
E_PAY = "5372819657105360167"
E_SETPAID = "5370664330847075805"
E_CALENDAR = "5372998306270035636"
E_FIND = "5373099637433450704"
E_STUDENTS = "5373116439345511510"

E_SLOTS = "5372998306270035636"
E_SLOT_ADD = "5373227270976584536"
E_HW_SUBMIT = "5377707548931543502"
E_HW_DONE = "5370664330847075805"
E_TRANSFER = "5372908279460542562"


def main_menu_student():
    b = [
        [
            InlineKeyboardButton(text="Мои занятия", callback_data="menu:lessons", icon_custom_emoji_id=E_LESSONS),
            InlineKeyboardButton(text="Напоминания", callback_data="menu:settings", icon_custom_emoji_id=E_SETTINGS),
        ],
        [
            InlineKeyboardButton(text="Домашки", callback_data="hw:list", icon_custom_emoji_id=E_HW),
            InlineKeyboardButton(text="Настройки ДЗ", callback_data="hw_rem_settings", icon_custom_emoji_id=E_HW_SETTINGS),
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
            InlineKeyboardButton(text="Слоты", callback_data="menu:slots", icon_custom_emoji_id=E_SLOTS),
        ],
        [
            InlineKeyboardButton(text="Найти", callback_data="menu:find", icon_custom_emoji_id=E_FIND),
            InlineKeyboardButton(text="Ученики", callback_data="menu:students", icon_custom_emoji_id=E_STUDENTS),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def time_picker_keyboard(selected_times=None):
    if selected_times is None:
        selected_times = set()
    hours = ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00"]
    b = []
    row = []
    for h in hours:
        mark = "✅" if h in selected_times else ""
        row.append(InlineKeyboardButton(text=f"{mark}{h}", callback_data=f"time:{h}"))
        if len(row) == 4:
            b.append(row)
            row = []
    if row:
        b.append(row)
    b.append([InlineKeyboardButton(text="💾 Сохранить выбранные", callback_data="time:save")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=b)


def timezone_offset_keyboard():
    b = [
        [InlineKeyboardButton(text="Москва (0)", callback_data="tz:0")],
        [InlineKeyboardButton(text="Владивосток (+7)", callback_data="tz:7")],
        [InlineKeyboardButton(text="Другой город", callback_data="tz:other")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def slots_menu_teacher():
    b = [
        [InlineKeyboardButton(text="Мои слоты", callback_data="slot:list", icon_custom_emoji_id=E_LIST)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def slots_picker_keyboard(slots, sid: int):
    b = []
    for s in slots[:10]:
        btn_text = s.datetime_start.strftime("%d.%m %H:%M")
        b.append([InlineKeyboardButton(text=btn_text, callback_data=f"act_slot:{sid}:{s.id}")])
    b.append([InlineKeyboardButton(text="Ввести дату вручную", callback_data=f"act_manual:{sid}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=b)


def student_transfer_menu():
    b = [
        [InlineKeyboardButton(text="Предложить время", callback_data="transfer:ask_slot", icon_custom_emoji_id=E_TRANSFER)],
        [InlineKeyboardButton(text="Уточнить у препода", callback_data="transfer:ask_teacher", icon_custom_emoji_id=E_FIND)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hw_submission_keyboard(hw_id: int):
    b = [
        [InlineKeyboardButton(text="Прикрепить фото/видео", callback_data=f"hw:attach:{hw_id}", icon_custom_emoji_id=E_HW_SUBMIT)],
        [InlineKeyboardButton(text="Я выполнил", callback_data=f"hw:finish:{hw_id}", icon_custom_emoji_id=E_HW_DONE)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def back_to_main(cb: str = "menu:main"):
    b = [[InlineKeyboardButton(text="⬅️ Назад", callback_data=cb)]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hours_keyboard():
    b = [
        [InlineKeyboardButton(text="1 час", callback_data="h:1"), InlineKeyboardButton(text="3 часа", callback_data="h:3")],
        [InlineKeyboardButton(text="1 день", callback_data="h:24"), InlineKeyboardButton(text="2 дня", callback_data="h:48")],
        [InlineKeyboardButton(text="Неделя", callback_data="h:168")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def pay_menu():
    b = [
        [InlineKeyboardButton(text="После урока", callback_data="pay:after", icon_custom_emoji_id=E_PAY)],
        [InlineKeyboardButton(text="Абонемент", callback_data="pay:end", icon_custom_emoji_id=E_HW)],
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
            InlineKeyboardButton(text="Занятие", callback_data=f"act:add:{student_id}", icon_custom_emoji_id=E_ADD),
            InlineKeyboardButton(text="Оплата", callback_data=f"act:pay:{student_id}", icon_custom_emoji_id=E_PAY),
        ],
        [InlineKeyboardButton(text="Удалить", callback_data=f"stdel:ask:{student_id}", icon_custom_emoji_id=E_DELETE)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
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
        [InlineKeyboardButton(text="4 зан.", callback_data=f"spa:{sid}:4"), InlineKeyboardButton(text="8 зан.", callback_data=f"spa:{sid}:8")],
        [InlineKeyboardButton(text="12 зан.", callback_data=f"spa:{sid}:12"), InlineKeyboardButton(text="16 зан.", callback_data=f"spa:{sid}:16")],
        [
            InlineKeyboardButton(text="➖ -1", callback_data=f"spa:{sid}:{current - 1}"),
            InlineKeyboardButton(text=f"Сейчас: {current}", callback_data="ignore"),
            InlineKeyboardButton(text="➕ +1", callback_data=f"spa:{sid}:{current + 1}"),
        ],
        [InlineKeyboardButton(text="❌ Обнулить", callback_data=f"spa:{sid}:0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="sp:open")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def confirm_delete_student_keyboard(sid: int):
    b = [[
        InlineKeyboardButton(text="Да", callback_data=f"stdel:{sid}", icon_custom_emoji_id=E_DELETE),
        InlineKeyboardButton(text="Нет", callback_data="menu:main", icon_custom_emoji_id=E_RESCHED),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def paid_button_keyboard():
    b = [
        [InlineKeyboardButton(text="Посмотреть абонементы", callback_data="show:tariffs", icon_custom_emoji_id=E_LIST)],
        [InlineKeyboardButton(text="Я оплатил(а)", callback_data="paid:click", icon_custom_emoji_id=E_PAY)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def back_from_paid_keyboard():
    b = [[InlineKeyboardButton(text="Отмена", callback_data="paid:back", icon_custom_emoji_id=E_DELETE)]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def transfer_keyboard():
    b = [[InlineKeyboardButton(text="Перенести", callback_data="transfer:click", icon_custom_emoji_id=E_RESCHED)]]
    return InlineKeyboardMarkup(inline_keyboard=b)


def transfer_cancel_keyboard():
    b = [[InlineKeyboardButton(text="Отмена", callback_data="transfer:cancel", icon_custom_emoji_id=E_DELETE)]]
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
            InlineKeyboardButton(text="Отмена", callback_data="menu:main", icon_custom_emoji_id=E_RESCHED),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hw_menu_teacher():
    b = [
        [InlineKeyboardButton(text="Создать ДЗ", callback_data="hw:create", icon_custom_emoji_id=E_ADD)],
        [InlineKeyboardButton(text="Все ДЗ", callback_data="hw:list_teacher", icon_custom_emoji_id=E_LIST)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def hw_reminder_keyboard(days: int, enabled: bool):
    btn_text = "Выключить" if enabled else "Включить"
    btn_icon = E_DELETE if enabled else E_HW_DONE
    b = [
        [InlineKeyboardButton(text=f"За {days} дн.", callback_data=f"hwrem:{days}")],
        [InlineKeyboardButton(text=btn_text, callback_data="hwrem:toggle", icon_custom_emoji_id=btn_icon)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=b)


def calendar_keyboard(year: int, month: int, days_with_lessons: set, free_slots_days: set = None, prefix: str = "cal"):
    kb = []
    month_name = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }[month]
    
    kb.append([
        InlineKeyboardButton(text="Пн", callback_data="cal:ignore"), InlineKeyboardButton(text="Вт", callback_data="cal:ignore"),
        InlineKeyboardButton(text="Ср", callback_data="cal:ignore"), InlineKeyboardButton(text="Чт", callback_data="cal:ignore"),
        InlineKeyboardButton(text="Пт", callback_data="cal:ignore"), InlineKeyboardButton(text="Сб", callback_data="cal:ignore"),
        InlineKeyboardButton(text="Вс", callback_data="cal:ignore"),
    ])
    
    if free_slots_days is None:
        free_slots_days = set()
        
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal:ignore"))
            else:
                mark = ""
                if day in days_with_lessons:
                    mark += "•"
                if day in free_slots_days:
                    mark += "🟢"
                
                btn_text = f"{day}{mark}"
                cb = f"{prefix}:day:{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(text=btn_text, callback_data=cb))
        kb.append(row)
    
    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1

    kb.append([
        InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:init:{prev_y}:{prev_m}"),
        InlineKeyboardButton(text=month_name, callback_data="cal:ignore"),
        InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:init:{next_y}:{next_m}"),
    ])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)


def slots_delete_keyboard(slots):
    b = []
    for s in slots[:20]: # Ограничиваем 20 слотами
        btn_text = f"❌ {s.datetime_start.strftime('%d.%m %H:%M')}"
        b.append([InlineKeyboardButton(text=btn_text, callback_data=f"slot:del:{s.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:slots")])
    return InlineKeyboardMarkup(inline_keyboard=b)