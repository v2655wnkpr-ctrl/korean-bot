import calendar
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TEACHER_LINK = "https://t.me/daru_usha"

# ТВОИ ПРЕМИУМ-ЭМОДЗИ КОРЕЙСКОГО БОТА
E_LESSONS = "5373052740685545765"
E_SETTINGS = "5373315390820596182"
E_HW = "5370664330847075805"
E_HW_SETTINGS = "5373107772101508671"
E_CONTACT = "5371038044541436659"
E_HELP = "5373099637433450704"
E_ADD = "5373035595176098840"
E_RESCHED = "5373272415377833505"
E_DELETE = "5373189118782095352"
E_LIST = "5373008304953901728"
E_STATS = "5373242857412903205"
E_PAY = "5371092693705310574"
E_SETPAID = "5371092693705310574"
E_CALENDAR = "5373120279046273354"
E_FIND = "5373107772101508671"
E_STUDENTS = "5262864719051504303"
E_SLOTS = "5373189118782095352"
E_SLOT_ADD = "5373107772101508671"
E_SLOT_LIST = "5373189118782095352"
E_BACK = "5372819657105360167"
E_HW_SUBMIT = "5377707548931543502"
E_HW_DONE = "5370664330847075805"
E_TRANSFER = "5373272415377833505"

def main_menu_student():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мои занятия", callback_data="menu:lessons", icon_custom_emoji_id=E_LESSONS), InlineKeyboardButton(text="Напоминания", callback_data="menu:settings", icon_custom_emoji_id=E_SETTINGS)],
        [InlineKeyboardButton(text="Домашки", callback_data="hw:list", icon_custom_emoji_id=E_HW), InlineKeyboardButton(text="Настройки дз", callback_data="hw_rem_settings", icon_custom_emoji_id=E_HW_SETTINGS)],
        [InlineKeyboardButton(text="Часовой пояс", callback_data="menu:timezone")],
        [InlineKeyboardButton(text="Связаться", url=TEACHER_LINK, icon_custom_emoji_id=E_CONTACT), InlineKeyboardButton(text="Помощь", callback_data="menu:help", icon_custom_emoji_id=E_HELP)],
    ])

def main_menu_teacher():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить занятие", callback_data="menu:add", icon_custom_emoji_id=E_ADD)],
        [InlineKeyboardButton(text="Перенести", callback_data="menu:reschedule", icon_custom_emoji_id=E_RESCHED), InlineKeyboardButton(text="Удалить", callback_data="menu:delete", icon_custom_emoji_id=E_DELETE)],
        [InlineKeyboardButton(text="Все занятия", callback_data="menu:list", icon_custom_emoji_id=E_LIST), InlineKeyboardButton(text="Статистика", callback_data="menu:stats", icon_custom_emoji_id=E_STATS)],
        [InlineKeyboardButton(text="Оплата", callback_data="menu:pay", icon_custom_emoji_id=E_PAY), InlineKeyboardButton(text="Добавить абонемент", callback_data="sp:open", icon_custom_emoji_id=E_SETPAID)],
        [InlineKeyboardButton(text="Домашки", callback_data="menu:hw", icon_custom_emoji_id=E_HW), InlineKeyboardButton(text="Календарь", callback_data="menu:calendar", icon_custom_emoji_id=E_CALENDAR)],
        [InlineKeyboardButton(text="Слоты", callback_data="menu:slots", icon_custom_emoji_id=E_SLOTS)],
        [InlineKeyboardButton(text="Найти", callback_data="menu:find", icon_custom_emoji_id=E_FIND), InlineKeyboardButton(text="Ученики", callback_data="menu:students", icon_custom_emoji_id=E_STUDENTS)],
        [InlineKeyboardButton(text="Часовой пояс", callback_data="menu:timezone")],
    ])

def timezone_offset_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Москва (0)", callback_data="tz:0")], [InlineKeyboardButton(text="Владивосток (+7)", callback_data="tz:7")], [InlineKeyboardButton(text="Другой город", callback_data="tz:other")]])

def calendar_keyboard(year, month, days_with_lessons, free_slots_days=None, prefix="cal"):
    kb = []
    month_name = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}[month]
    kb.append([InlineKeyboardButton(text=d, callback_data="cal:ignore") for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]])
    if free_slots_days is None: free_slots_days = set()
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0: row.append(InlineKeyboardButton(text=" ", callback_data="cal:ignore"))
            else:
                mark = ""
                if day in days_with_lessons: mark += "•"
                if day in free_slots_days: mark += "🟢"
                row.append(InlineKeyboardButton(text=f"{day}{mark}", callback_data=f"{prefix}:day:{year}-{month:02d}-{day:02d}"))
        kb.append(row)
    prev_m = month - 1 if month > 1 else 12
    prev_y = year if month > 1 else year - 1
    next_m = month + 1 if month < 12 else 1
    next_y = year if month < 12 else year + 1
    kb.append([InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:init:{prev_y}:{prev_m}"), InlineKeyboardButton(text=month_name, callback_data="cal:ignore"), InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:init:{next_y}:{next_m}")])
    back_cb = "menu:slots" if prefix == "slot" else "menu:main"
    kb.append([InlineKeyboardButton(text="Назад", callback_data=back_cb, icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def time_picker_keyboard(selected_times=None):
    if selected_times is None: selected_times = set()
    hours = ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00"]
    b, row = [], []
    for h in hours:
        mark = "✅" if h in selected_times else ""
        row.append(InlineKeyboardButton(text=f"{mark}{h}", callback_data=f"time:{h}"))
        if len(row) == 4: b.append(row); row = []
    if row: b.append(row)
    b.append([InlineKeyboardButton(text="💾 Сохранить выбранные", callback_data="time:save")])
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:slots", icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=b)

def slots_menu_teacher():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть слоты", callback_data="slot:show_calendar", icon_custom_emoji_id=E_SLOT_ADD)], [InlineKeyboardButton(text="Мои открытые слоты", callback_data="slot:list", icon_custom_emoji_id=E_SLOT_LIST)], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])

def slots_delete_keyboard(slots):
    b = [[InlineKeyboardButton(text=f"❌ {s.datetime_start.strftime('%d.%m %H:%M')}", callback_data=f"slot:del:{s.id}")] for s in slots[:20]]
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:slots", icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=b)

def back_to_main(cb="menu:main"): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data=cb, icon_custom_emoji_id=E_BACK)]])
def hours_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="1 час", callback_data="h:1"), InlineKeyboardButton(text="3 часа", callback_data="h:3")], [InlineKeyboardButton(text="1 день", callback_data="h:24"), InlineKeyboardButton(text="2 дня", callback_data="h:48")], [InlineKeyboardButton(text="Неделя", callback_data="h:168")], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def pay_menu(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="После урока", callback_data="pay:after", icon_custom_emoji_id=E_PAY)], [InlineKeyboardButton(text="Абонемент", callback_data="pay:end", icon_custom_emoji_id=E_PAY)], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def card_keyboard(sid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Занятие", callback_data=f"act:add:{sid}", icon_custom_emoji_id=E_ADD), InlineKeyboardButton(text="Оплата", callback_data=f"act:pay:{sid}", icon_custom_emoji_id=E_PAY)], [InlineKeyboardButton(text="✏️ Изменить имя", callback_data=f"stdel:setname:{sid}")], [InlineKeyboardButton(text="Удалить", callback_data=f"stdel:ask:{sid}", icon_custom_emoji_id=E_DELETE)], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def set_paid_students_keyboard(students): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s.custom_name or s.full_name, callback_data=f"sp:{s.id}")] for s in students] + [[InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def set_paid_amounts_keyboard(sid, current): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="4 зан.", callback_data=f"spa:{sid}:4"), InlineKeyboardButton(text="8 зан.", callback_data=f"spa:{sid}:8")], [InlineKeyboardButton(text="➖ -1", callback_data=f"spa:{sid}:{current-1}"), InlineKeyboardButton(text=f"Сейчас: {current}", callback_data="ignore"), InlineKeyboardButton(text="➕ +1", callback_data=f"spa:{sid}:{current+1}")], [InlineKeyboardButton(text="Обнулить", callback_data=f"spa:{sid}:0", icon_custom_emoji_id=E_DELETE)], [InlineKeyboardButton(text="Назад", callback_data="sp:open", icon_custom_emoji_id=E_BACK)]])
def confirm_delete_student_keyboard(sid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Да", callback_data=f"stdel:{sid}", icon_custom_emoji_id=E_DELETE), InlineKeyboardButton(text="Нет", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def paid_button_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Посмотреть абонементы", callback_data="show:tariffs", icon_custom_emoji_id=E_LIST)], [InlineKeyboardButton(text="Я оплатил(а)", callback_data="paid:click", icon_custom_emoji_id=E_PAY)]])
def back_from_paid_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="paid:back", icon_custom_emoji_id=E_DELETE)]])
def transfer_cancel_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="transfer:cancel", icon_custom_emoji_id=E_DELETE)]])
def lessons_action_keyboard(lessons, action): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{l.datetime_start.strftime('%d.%m %H:%M')} — {l.title}", callback_data=f"{action}:{l.id}")] for l in lessons[:15]] + [[InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def confirm_delete_keyboard(lid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Удалить", callback_data=f"confirm_del:{lid}", icon_custom_emoji_id=E_DELETE), InlineKeyboardButton(text="Отмена", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])

def hw_menu_teacher():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Создать ДЗ", callback_data="hw:create", icon_custom_emoji_id=E_ADD)], [InlineKeyboardButton(text="👤 Назначить ДЗ", callback_data="hw:assign_menu")], [InlineKeyboardButton(text="Все ДЗ", callback_data="hw:list_teacher", icon_custom_emoji_id=E_LIST)], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])

def hw_reminder_keyboard(enabled): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Выключить напоминания" if enabled else "Включить напоминания", callback_data="hwrem:toggle", icon_custom_emoji_id=E_DELETE if enabled else E_HW_DONE)], [InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)]])
def hw_submission_keyboard(hw_id): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Прикрепить фото/видео", callback_data=f"hw:attach:{hw_id}", icon_custom_emoji_id=E_HW_SUBMIT)], [InlineKeyboardButton(text="Я выполнил", callback_data=f"hw:finish:{hw_id}", icon_custom_emoji_id=E_HW_DONE)]])

def hw_assign_students_kb(students):
    b = [[InlineKeyboardButton(text="👥 Всем", callback_data="hw:assign_stud:all")]]
    for s in students: b.append([InlineKeyboardButton(text=s.custom_name or s.full_name, callback_data=f"hw:assign_stud:{s.id}")])
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:hw", icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=b)

def hw_assign_list_kb(hws, student_id):
    b = [[InlineKeyboardButton(text=hw.title, callback_data=f"hw:assign_do:{student_id}:{hw.id}")] for hw in hws[:15]]
    b.append([InlineKeyboardButton(text="Назад", callback_data="hw:assign_menu", icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=b)

def hw_view_teacher_keyboard(hw_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать текст", callback_data=f"hw:edit_text:{hw_id}")], [InlineKeyboardButton(text="Удалить ДЗ", callback_data=f"hw:del_ask:{hw_id}", icon_custom_emoji_id=E_DELETE)], [InlineKeyboardButton(text="Назад", callback_data="hw:list_teacher", icon_custom_emoji_id=E_BACK)]])
def lesson_time_keyboard(date_str: str):
    hours = ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00"]
    b, row = [], []
    for h in hours:
        row.append(InlineKeyboardButton(text=h, callback_data=f"actcal:time:{date_str}:{h}"))
        if len(row) == 4: b.append(row); row = []
    if row: b.append(row)
    b.append([InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="actcal:manual")])
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=b)
