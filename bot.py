import logging
import os
from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from sqlalchemy import select

from database import init_db, async_session
from models import (
    Student, Lesson, Homework, HomeworkDone, 
    LessonSlot, HomeworkSubmission
)
from scheduler import start_scheduler, now_msk
from texts import (
    text_pay_after, text_pay_end, text_tariffs, text_help, hours_text,
    text_pay_after_button, text_pay_end_button, text_payment_received,
    text_welcome, text_transfer_ask, text_transfer_sent, text_transfer_cancel,
    text_hw_add_deadline, text_hw_reminder_settings, text_hw_reminder_off, text_hw_reminder_on,
)
from keyboards import (
    main_menu_student, main_menu_teacher, back_to_main, hours_keyboard,
    pay_menu, tariffs_keyboard, card_keyboard, set_paid_students_keyboard,
    set_paid_amounts_keyboard, paid_button_keyboard, back_from_paid_keyboard,
    transfer_cancel_keyboard, lessons_action_keyboard, confirm_delete_keyboard,
    confirm_delete_student_keyboard, hw_menu_teacher, hw_reminder_keyboard,
    calendar_keyboard, timezone_offset_keyboard, TEACHER_LINK,
    slots_menu_teacher, student_transfer_menu, hw_submission_keyboard,
    time_picker_keyboard, slots_picker_keyboard, slots_delete_keyboard,
    student_lesson_reminders_keyboard, subscription_payment_keyboard, # <-- ДОБАВЛЕНО
    E_ADD, E_LIST, E_DELETE
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = 803167669

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

BASE_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://localhost").rstrip("/")
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret-token"
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class AddLesson(StatesGroup):
    student = State()
    dt = State()
    title = State()

class SetTimezone(StatesGroup):
    choosing_tz = State()

class PayFlow(StatesGroup):
    choosing_student = State()

class FindStudent(StatesGroup):
    query = State()

class RescheduleFlow(StatesGroup):
    dt = State()

class AddHomework(StatesGroup):
    title = State()
    text = State()
    media = State()
    deadline = State()

class SubmitHW(StatesGroup):
    media = State()

class PaymentProof(StatesGroup):
    waiting_photo = State()

def is_teacher(uid: int) -> bool:
    return uid == TEACHER_ID


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = message.from_user
    uid = user.id
    is_new = False

    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()

        if student is None:
            is_new = True
            student = Student(tg_id=uid, full_name=user.full_name, username=user.username)
            session.add(student)
            await session.commit()

            if uid != TEACHER_ID:
                un = user.username or "—"
                text = f"🆕 Новый ученик!\n\n{user.full_name}\n@{un}\nID: {uid}"
                try:
                    await bot.send_message(TEACHER_ID, text)
                except Exception as e:
                    logging.error(f"Ош: {e}")

    if is_new and not is_teacher(uid):
        await message.answer("Выбери свой часовой пояс:", reply_markup=timezone_offset_keyboard())
        await state.set_state(SetTimezone.choosing_tz)
        return

    if is_teacher(uid):
        text = "👋 Привет, преподаватель!\n\nВыбери действие:"
        kb = main_menu_teacher()
    else:
        text = f"👋 Привет, {user.full_name}!\n\nВыбери действие:"
        kb = main_menu_student()

    await message.answer(text, reply_markup=kb)


@dp.callback_query(lambda c: c.data.startswith("tz:"), SetTimezone.choosing_tz)
async def cb_set_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tz_val = callback.data.split(":")[1]
    if tz_val == "other":
        await callback.message.edit_text("Напиши, на сколько часов твое время отличается от Москвы:")
        return
    
    offset = int(tz_val)
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        if student:
            student.timezone_offset = offset
            await session.commit()
    
    await callback.message.edit_text("✅ Часовой пояс установлен!")
    await callback.message.answer(text_welcome(), reply_markup=main_menu_student())
    await state.clear()

@dp.message(SetTimezone.choosing_tz)
async def set_tz_text(message: types.Message, state: FSMContext):
    try:
        offset = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, напиши просто число:")
        return
        
    uid = message.from_user.id
    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        if student:
            student.timezone_offset = offset
            await session.commit()
    
    await message.answer("✅ Часовой пояс установлен!")
    await message.answer(text_welcome(), reply_markup=main_menu_student())
    await state.clear()


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    uid = message.from_user.id
    if is_teacher(uid):
        kb = main_menu_teacher()
    else:
        kb = main_menu_student()
    await message.answer("Главное меню:", reply_markup=kb)


# ---------- КАЛЕНДАРЬ ----------
@dp.callback_query(lambda c: c.data == "menu:calendar")
async def cb_calendar(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    now = now_msk()
    year, month = now.year, now.month
    async with async_session() as session:
        q = select(Lesson).where(Lesson.datetime_start >= datetime(year, month, 1))
        r = await session.execute(q)
        lessons = r.scalars().all()
        q_slots = select(LessonSlot).where(LessonSlot.is_booked == False)
        r_slots = await session.execute(q_slots)
        slots = r_slots.scalars().all()
    days_lessons = {l.datetime_start.day for l in lessons if l.datetime_start.month == month}
    days_slots = {s.datetime_start.day for s in slots if s.datetime_start.month == month}
    kb = calendar_keyboard(year, month, days_lessons, days_slots)
    await callback.message.edit_text("📅 Твой календарь (🟢 = есть слоты):", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("cal:init:"))
async def cb_calendar_init(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    _, _, y, m = callback.data.split(":")
    y, m = int(y), int(m)
    async with async_session() as session:
        q = select(Lesson).where(Lesson.datetime_start >= datetime(y, m, 1))
        r = await session.execute(q)
        lessons = r.scalars().all()
        q_slots = select(LessonSlot).where(LessonSlot.is_booked == False)
        r_slots = await session.execute(q_slots)
        slots = r_slots.scalars().all()
    days_lessons = {l.datetime_start.day for l in lessons if l.datetime_start.month == m}
    days_slots = {s.datetime_start.day for s in slots if s.datetime_start.month == m}
    kb = calendar_keyboard(y, m, days_lessons, days_slots)
    await callback.message.edit_text("📅 Твой календарь (🟢 = есть слоты):", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "cal:ignore")
async def cb_cal_ignore(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:day:"))
async def cb_cal_day(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    date_str = callback.data.split(":")[2]
    y, m, d = map(int, date_str.split("-"))
    dt_start = datetime(y, m, d, 0, 0)
    dt_end = datetime(y, m, d, 23, 59)
    async with async_session() as session:
        q = select(Lesson).where(Lesson.datetime_start >= dt_start, Lesson.datetime_start <= dt_end).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
        q_slots = select(LessonSlot).where(LessonSlot.datetime_start >= dt_start, LessonSlot.datetime_start <= dt_end, LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start)
        r_slots = await session.execute(q_slots)
        slots = r_slots.scalars().all()

    lines = [f"📅 {d}.{m:02d}.{y}\n"]
    if lessons:
        lines.append("Занятия:")
        for l in lessons:
            lines.append(f"• {l.datetime_start.strftime('%H:%M')} — {l.title}")
        lines.append("")
    if slots:
        lines.append("Свободные слоты:")
        for s in slots:
            lines.append(f"🟢 {s.datetime_start.strftime('%H:%M')}")
    if not lessons and not slots:
        lines.append("Занятий и слотов нет.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:calendar"))


# ---------- СЛОТЫ ----------
@dp.callback_query(lambda c: c.data == "menu:slots")
async def cb_slots_menu(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await callback.message.edit_text("📅 Управление слотами:", reply_markup=slots_menu_teacher())

@dp.callback_query(lambda c: c.data == "slot:show_calendar")
async def cb_slot_show_calendar(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    now = now_msk()
    year, month = now.year, now.month
    async with async_session() as session:
        q = select(LessonSlot).where(LessonSlot.is_booked == False)
        r = await session.execute(q)
        slots = r.scalars().all()
    days_slots = {s.datetime_start.day for s in slots if s.datetime_start.month == month}
    kb = calendar_keyboard(year, month, set(), days_slots, prefix="slot")
    await callback.message.edit_text("📅 Выбери день, чтобы открыть слоты:\n(🟢 — уже есть свободные)", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("slot:day:"))
async def cb_slot_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    date_str = callback.data.split(":")[2]
    y, m, d = map(int, date_str.split("-"))
    dt_start = datetime(y, m, d, 0, 0)
    await state.update_data(date_str=dt_start.strftime("%Y-%m-%d"), selected_times=[])
    await callback.message.edit_text(f"📅 {d}.{m:02d}.{y}\n\nВыбери время (можно несколько):", reply_markup=time_picker_keyboard())

@dp.callback_query(lambda c: c.data.startswith("slot:init:"))
async def cb_slot_init(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    _, _, y, m = callback.data.split(":")
    y, m = int(y), int(m)
    async with async_session() as session:
        q = select(LessonSlot).where(LessonSlot.is_booked == False)
        r = await session.execute(q)
        slots = r.scalars().all()
    days_slots = {s.datetime_start.day for s in slots if s.datetime_start.month == m}
    kb = calendar_keyboard(y, m, set(), days_slots, prefix="slot")
    await callback.message.edit_text("📅 Выбери день, чтобы открыть слоты:\n(🟢 — уже есть свободные)", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("time:"))
async def cb_time_pick(callback: CallbackQuery, state: FSMContext):
    time_str = callback.data.split(":", 1)[1]
    data = await state.get_data()
    date_str = data.get("date_str")
    if not date_str:
        await callback.answer("❌ Ошибка: дата не найдена. Начни заново.", show_alert=True)
        await state.clear()
        return
    if time_str == "save":
        selected = data.get("selected_times", [])
        if not selected:
            await callback.answer("Ты не выбрал ни одного времени!", show_alert=True)
            return
        async with async_session() as session:
            for t in selected:
                dt = datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M")
                slot = LessonSlot(teacher_id=TEACHER_ID, datetime_start=dt)
                session.add(slot)
            await session.commit()
        await callback.message.edit_text(f"✅ Открыто слотов: {len(selected)}", reply_markup=slots_menu_teacher())
        await state.clear()
        await callback.answer()
        return
    selected = data.get("selected_times", [])
    if time_str in selected: selected.remove(time_str)
    else: selected.append(time_str)
    await state.update_data(selected_times=selected)
    await callback.message.edit_reply_markup(reply_markup=time_picker_keyboard(set(selected)))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "slot:list")
async def cb_slot_list(callback: CallbackQuery):
    await callback.answer()
    now = now_msk()
    async with async_session() as session:
        q = select(LessonSlot).where(LessonSlot.teacher_id == TEACHER_ID, LessonSlot.is_booked == False, LessonSlot.datetime_start >= now).order_by(LessonSlot.datetime_start)
        r = await session.execute(q)
        slots = r.scalars().all()
    if not slots:
        await callback.message.edit_text("Нет свободных слотов.", reply_markup=slots_menu_teacher())
        return
    kb = slots_delete_keyboard(slots)
    await callback.message.edit_text("📅 <b>Твои свободные слоты:</b>\n\nНажми на слот ❌, чтобы закрыть его:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("slot:del:"))
async def cb_slot_del(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    slot_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        if slot and not slot.is_booked:
            await session.delete(slot)
            await session.commit()
            await callback.message.answer(f"✅ Слот на {slot.datetime_start.strftime('%d.%m %H:%M')} закрыт.")
    await cb_slot_list(callback)


# ---------- СТАТИСТИКА / ДОБАВЛЕНИЕ ЗАНЯТИЙ ----------
@dp.callback_query(lambda c: c.data == "menu:stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r_students = await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))
        students_count = len(r_students.scalars().all())
        r_lessons = await session.execute(select(Lesson))
        lessons_count = len(r_lessons.scalars().all())
        now = now_msk()
        r_future = await session.execute(select(Lesson).where(Lesson.datetime_start >= now))
        future_count = len(r_future.scalars().all())
        r_slots = await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False, LessonSlot.datetime_start >= now))
        slots_count = len(r_slots.scalars().all())
    text = f"📊 <b>Статистика</b>\n\n👥 Учеников: {students_count}\n📚 Всего занятий: {lessons_count}\n📅 Предстоящих занятий: {future_count}\n🟢 Свободных слотов: {slots_count}"
    await callback.message.edit_text(text, reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    if not is_teacher(uid): return
    async with async_session() as session:
        result = await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))
        students = result.scalars().all()
    if not students:
        await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
        return
    lines = ["👥 Выбери ученика:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
    lines.append(f"\nНапиши номер 1–{len(students)}")
    data = {"total": len(students)}
    for i, s in enumerate(students, 1):
        data[f"s_{i}"] = s.id
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    state_ctx = dp.fsm.get_context(bot=bot, chat_id=callback.message.chat.id, user_id=uid)
    await state_ctx.update_data(**data)
    await state_ctx.set_state(AddLesson.student)

@dp.message(AddLesson.student)
async def add_student(message: types.Message, state: FSMContext):
    data = await state.get_data()
    total = data.get("total", 0)
    txt = message.text.strip()
    sid = None
    if txt.isdigit():
        num = int(txt)
        if 1 <= num <= total: sid = data.get(f"s_{num}")
    if sid is None:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            r = await session.execute(select(Student))
            all_s = r.scalars().all()
        for s in all_s:
            if s.tg_id == TEACHER_ID: continue
            un = (s.username or "").lower()
            nm = s.full_name.lower()
            if low == un or low in nm:
                sid = s.id
                break
    if sid is None:
        await message.answer("Не нашёл.")
        return
    async with async_session() as session:
        student = await session.get(Student, sid)
    if not student:
        await message.answer("Ученик не найден.")
        await state.clear()
        return
    await state.update_data(sid=student.id, sname=student.full_name)
    async with async_session() as session:
        r = await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))
        slots = r.scalars().all()
    if slots:
        kb = slots_picker_keyboard(slots, sid)
        await message.answer("Выбери свободный слот или введи дату вручную:", reply_markup=kb)
        return
    await message.answer("Введи дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("act_slot:"))
async def cb_act_slot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, sid_str, slot_id_str = callback.data.split(":")
    sid, slot_id = int(sid_str), int(slot_id_str)
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        student = await session.get(Student, sid)
        if not slot or not student: return
        slot.is_booked = True
        await session.commit()
        await state.update_data(sid=student.id, sname=student.full_name, dt=slot.datetime_start, slot_id=slot.id)
    await callback.message.edit_text("Введи название занятия (или «-»):")
    await state.set_state(AddLesson.title)

@dp.callback_query(lambda c: c.data.startswith("act_manual:"))
async def cb_act_manual(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = await session.get(Student, sid)
        if not student: return
        await state.update_data(sid=student.id, sname=student.full_name)
    await callback.message.edit_text("Введи дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(AddLesson.dt)

@dp.message(AddLesson.dt)
async def add_dt(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
    await state.update_data(dt=dt)
    await message.answer("Название (или «-» = Корейский):")
    await state.set_state(AddLesson.title)

@dp.message(AddLesson.title)
async def add_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip()
    if title == "-": title = "Корейский"
    async with async_session() as session:
        lesson = Lesson(student_id=data["sid"], datetime_start=data["dt"], title=title)
        session.add(lesson)
        await session.commit()
    dt = data["dt"]
    text = f"✅ Занятие добавлено!\n\nУченик: {data['sname']}\nДата: {dt.strftime('%d.%m.%Y %H:%M')}\nНазвание: {title}"
    await message.answer(text, reply_markup=main_menu_teacher())
    await state.clear()

# ---------- ДЗ ----------
@dp.callback_query(lambda c: c.data == "menu:hw")
async def cb_hw_menu(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await callback.message.edit_text("📚 Домашние задания", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:create")
async def cb_hw_create(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Введи название темы ДЗ:")
    await state.set_state(AddHomework.title)

@dp.message(AddHomework.title)
async def hw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Теперь введи текст задания:")
    await state.set_state(AddHomework.text)

@dp.message(AddHomework.text)
async def hw_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Прикрепи материал (перешли видео из канала). Или напиши «-»:")
    await state.set_state(AddHomework.media)

@dp.message(AddHomework.media)
async def hw_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    m_type, m_id, c_id = None, None, None
    if message.video:
        m_type, m_id, c_id = "video", str(message.message_id), message.chat.id
    elif message.photo:
        m_type, m_id, c_id = "photo", str(message.message_id), message.chat.id
    elif message.text == "-":
        pass
    else:
        await message.answer("Пришли видео или «-»:")
        return
    await state.update_data(media_type=m_type, media_id=m_id, chat_id=c_id)
    await message.answer(text_hw_add_deadline())
    await state.set_state(AddHomework.deadline)

@dp.message(AddHomework.deadline)
async def hw_deadline(message: types.Message, state: FSMContext):
    data = await state.get_data()
    txt = message.text.strip()
    deadline = None
    if txt != "-":
        try:
            deadline = datetime.strptime(txt, "%d.%m.%Y")
        except ValueError:
            await message.answer("Неверный формат. Пример: 25.10.2026 или «-»")
            return
    async with async_session() as session:
        hw = Homework(title=data["title"], text=data["text"], media_type=data.get("media_type"), media_id=data.get("media_id"), chat_id=data.get("chat_id"), deadline=deadline)
        session.add(hw)
        await session.commit()
    await message.answer("✅ ДЗ создано!", reply_markup=main_menu_teacher())
    await state.clear()

@dp.callback_query(lambda c: c.data == "hw:list_teacher")
async def cb_hw_list_teacher(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        res = await session.execute(select(Homework).order_by(Homework.id.desc()))
        hws = res.scalars().all()
    if not hws:
        await callback.message.edit_text("Пока нет созданных ДЗ.", reply_markup=hw_menu_teacher())
        return
    b = []
    for hw in hws:
        dt = hw.created_at.strftime("%d.%m")
        b.append([InlineKeyboardButton(text=f"{dt} — {hw.title}", callback_data=f"hw:view_teacher:{hw.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:hw")])
    kb = InlineKeyboardMarkup(inline_keyboard=b)
    await callback.message.edit_text("📚 Выбери ДЗ (для просмотра/удаления):", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:view_teacher:"))
async def cb_hw_view_teacher(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
    if not hw: return
    text = f"📚 {hw.title}\n\n{hw.text}"
    if hw.deadline: text += f"\n\n📅 Дедлайн: {hw.deadline.strftime('%d.%m.%Y')}"
    if hw.media_type: text += f"\n\n📎 Прикреплен материал ({hw.media_type})"
    b = [
        [InlineKeyboardButton(text="🗑 Удалить ДЗ", callback_data=f"hw:del_ask:{hw.id}", icon_custom_emoji_id=E_DELETE)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="hw:list_teacher")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=b)
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:del_ask:"))
async def cb_hw_del_ask(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
    if not hw: return
    text = f"Точно удалить ДЗ?\n\n{hw.title}"
    b = [
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"hw:del:{hw.id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"hw:view_teacher:{hw.id}")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=b)
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:del:"))
async def cb_hw_del(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    hw_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
        if hw:
            r_done = await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id))
            for d in r_done.scalars().all(): await session.delete(d)
            r_sub = await session.execute(select(HomeworkSubmission).where(HomeworkSubmission.homework_id == hw_id))
            for s in r_sub.scalars().all(): await session.delete(s)
            await session.delete(hw)
            await session.commit()
    await callback.message.edit_text("✅ ДЗ удалено.", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:list")
async def cb_hw_list(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        res = await session.execute(select(Homework).order_by(Homework.id.desc()))
        hws = res.scalars().all()
    if not hws:
        await callback.message.edit_text("Пока нет ДЗ.", reply_markup=back_to_main())
        return
    b = [[InlineKeyboardButton(text=hw.title, callback_data=f"hw:view:{hw.id}")] for hw in hws]
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=b)
    await callback.message.edit_text("📚 Выбери тему:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:view:"))
async def cb_hw_view(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        done = None
        if st:
            r2 = await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id, HomeworkDone.student_id == st.id))
            done = r2.scalar_one_or_none()
    if not hw: return
    text = f"📚 {hw.title}\n\n{hw.text}"
    if hw.deadline: text += f"\n\n📅 Дедлайн: {hw.deadline.strftime('%d.%m.%Y')}"
    kb = hw_submission_keyboard(hw.id)
    if done:
        text += "\n\n✅ Вы уже отметили это задание."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="hw:list")]])
    else:
        text += "\n\nПрикрепи фото/видео и нажми «Выполнил»."
    try:
        if hw.media_type in ("photo", "video") and hw.chat_id:
            await bot.copy_message(chat_id=callback.from_user.id, from_chat_id=hw.chat_id, message_id=int(hw.media_id), caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:attach:"))
async def cb_hw_attach(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    await state.update_data(hw_id=hw_id)
    await callback.message.edit_text("Отправь фото или видео:")
    await state.set_state(SubmitHW.media)

@dp.message(SubmitHW.media)
async def process_hw_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    hw_id = data.get("hw_id")
    if not message.photo and not message.video:
        await message.answer("Нужно фото или видео.")
        return
    m_type = "photo" if message.photo else "video"
    m_id = message.photo[-1].file_id if message.photo else message.video.file_id
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == message.from_user.id))
        st = r.scalar_one_or_none()
        if st:
            sub = HomeworkSubmission(homework_id=hw_id, student_id=st.id, media_type=m_type, media_id=m_id)
            session.add(sub)
            await session.commit()
            if m_type == "photo":
                await bot.send_photo(TEACHER_ID, photo=m_id, caption=f"📚 {st.full_name} прикрепил фото к ДЗ")
            else:
                await bot.send_video(TEACHER_ID, video=m_id, caption=f"📚 {st.full_name} прикрепил видео к ДЗ")
    await message.answer("✅ Файл прикреплен. Можешь нажать «Выполнил».")

@dp.callback_query(lambda c: c.data.startswith("hw:finish:"))
async def cb_hw_finish(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        hw = await session.get(Homework, hw_id)
        if st and hw:
            r2 = await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id, HomeworkDone.student_id == st.id))
            if not r2.scalar_one_or_none():
                done = HomeworkDone(homework_id=hw_id, student_id=st.id)
                session.add(done)
                await session.commit()
                await bot.send_message(TEACHER_ID, f"📚 {st.full_name} сдал ДЗ: {hw.title}")
    await callback.message.edit_text("✅ Отлично! Я передал преподавателю.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "hw_rem_settings")
async def cb_hw_rem_settings(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
    if not st: return
    enabled = st.hw_reminder_enabled
    status = "✅ Включены" if enabled else "❌ Выключены"
    txt = f"⚙️ <b>Напоминания о ДЗ</b>\n\nЕсли включено, я буду каждый вечер напоминать тебе о невыполненных заданиях.\n\nСтатус: <b>{status}</b>"
    kb = hw_reminder_keyboard(enabled)
    await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "hwrem:toggle")
async def cb_hwrem_toggle(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        if st:
            st.hw_reminder_enabled = not st.hw_reminder_enabled
            await session.commit()
    await cb_hw_rem_settings(callback)


@dp.callback_query(lambda c: c.data == "menu:lessons")
async def cb_student_lessons(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        if not st: return
        now = now_msk()
        r_up = await session.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start >= now).order_by(Lesson.datetime_start))
        upcoming = r_up.scalars().all()
        r_past = await session.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start < now).order_by(Lesson.datetime_start.desc()).limit(5))
        past = r_past.scalars().all()
    lines = ["📅 <b>Твои занятия:</b>\n"]
    if upcoming:
        lines.append("<b>Предстоящие:</b>")
        for l in upcoming:
            local_dt = l.datetime_start + timedelta(hours=st.timezone_offset)
            lines.append(f"• {local_dt.strftime('%d.%m %H:%M')} — {l.title}")
        lines.append("")
    else:
        lines.append("У тебя нет предстоящих занятий.\n")
    if past:
        lines.append("<b>Прошедшие (последние 5):</b>")
        for l in past:
            local_dt = l.datetime_start + timedelta(hours=st.timezone_offset)
            lines.append(f"✓ {local_dt.strftime('%d.%m %H:%M')} — {l.title}")
    kb_buttons = []
    if upcoming:
        kb_buttons.append([InlineKeyboardButton(text="🔄 Перенести занятие", callback_data="transfer:click", icon_custom_emoji_id=E_RESCHED)])
    kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "menu:settings")
async def cb_settings_menu(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
    if not st: return
    hours = st.lesson_reminder_hours if st.lesson_reminder_hours is not None else 2
    text = f"⚙️ <b>Настройки напоминаний</b>\n\nЗа сколько часов до начала занятия тебе напоминать?\nСейчас: <b>за {hours} ч.</b>\n\n<i>(Ссылка на урок всегда приходит за 30 минут)</i>"
    kb = student_lesson_reminders_keyboard(hours)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("lrem:"))
async def cb_lrem_hours(callback: CallbackQuery):
    await callback.answer()
    hours = int(callback.data.split(":")[1])
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        if st:
            st.lesson_reminder_hours = hours
            await session.commit()
    await callback.answer(f"Будем напоминать за {hours} ч. до урока", show_alert=True)
    await cb_settings_menu(callback)


@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Как хочешь перенести?", reply_markup=student_transfer_menu())

@dp.callback_query(lambda c: c.data == "transfer:ask_slot")
async def cb_transfer_ask_slot(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        r = await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))
        slots = r.scalars().all()
    if not slots:
        await callback.message.edit_text("Свободных слотов нет. Уточни у преподавателя.", reply_markup=back_to_main())
        return
    b = []
    for s in slots[:10]:
        b.append([InlineKeyboardButton(text=s.datetime_start.strftime("%d.%m %H:%M"), callback_data=f"transfer:pick:{s.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=b)
    await callback.message.edit_text("Выбери свободное время:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("transfer:pick:"))
async def cb_transfer_pick(callback: CallbackQuery):
    await callback.answer()
    slot_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        if not st or not slot: return
        now = now_msk()
        r2 = await session.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start >= now).order_by(Lesson.datetime_start))
        lesson = r2.scalars().first()
        if not lesson:
            await callback.message.edit_text("У тебя нет предстоящих занятий для переноса.", reply_markup=back_to_main())
            return
        les_info = lesson.datetime_start.strftime("%d.%m %H:%M")
        text = f"🔄 Запрос на перенос\n\nУченик: {st.full_name}\nТекущее: {les_info}\nХочет: {slot.datetime_start.strftime('%d.%m %H:%M')}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"transfer:approve:{lesson.id}:{slot.id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"transfer:decline:{slot.id}")]
        ])
        await bot.send_message(TEACHER_ID, text, reply_markup=kb)
        slot.is_booked = True
        await session.commit()
    await callback.message.edit_text("✅ Запрос отправлен преподавателю! Жди подтверждения.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data.startswith("transfer:approve:"))
async def cb_transfer_approve(callback: CallbackQuery):
    await callback.answer("Перенос подтвержден")
    if not is_teacher(callback.from_user.id): return
    _, _, lesson_id_str, slot_id_str = callback.data.split(":")
    lesson_id, slot_id = int(lesson_id_str), int(slot_id_str)
    async with async_session() as session:
        lesson = await session.get(Lesson, lesson_id)
        slot = await session.get(LessonSlot, slot_id)
        if lesson and slot:
            lesson.datetime_start = slot.datetime_start
            await session.delete(slot)
            await session.commit()
            await callback.message.edit_text("✅ Вы подтвердили перенос.")
            r = await session.execute(select(Student).where(Student.id == lesson.student_id))
            st = r.scalar_one_or_none()
            if st:
                await bot.send_message(st.tg_id, f"✅ Преподаватель подтвердил перенос!\nНовое время: {lesson.datetime_start.strftime('%d.%m %H:%M')}")

@dp.callback_query(lambda c: c.data.startswith("transfer:decline:"))
async def cb_transfer_decline(callback: CallbackQuery):
    await callback.answer("Перенос отклонен")
    if not is_teacher(callback.from_user.id): return
    slot_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        if slot:
            slot.is_booked = False
            await session.commit()
    await callback.message.edit_text("❌ Вы отклонили перенос. Слот снова свободен.")


# ---------- ОПЛАТА ----------
@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await callback.message.edit_text("💰 Оплата и напоминания\n\nЧто отправить?", reply_markup=pay_menu())

@dp.callback_query(lambda c: c.data.startswith("pay:"))
async def cb_pay_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    if not is_teacher(uid): return
    mode = callback.data.split(":")[1]
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))
        students = r.scalars().all()
    if not students:
        await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main("menu:pay"))
        return
    lines = ["👥 Кому:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
    lines.append(f"\nНомер 1–{len(students)} или @username:")
    data = {"mode": mode, "total": len(students)}
    for i, s in enumerate(students, 1):
        data[f"st_{i}"] = s.tg_id
    await state.update_data(**data)
    await state.set_state(PayFlow.choosing_student)
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:pay"))

@dp.message(PayFlow.choosing_student)
async def pay_send(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    data = await state.get_data()
    total = data.get("total", 0)
    mode = data.get("mode")
    txt = message.text.strip()
    tg = None
    if txt.isdigit():
        num = int(txt)
        if 1 <= num <= total: tg = data.get(f"st_{num}")
    if tg is None:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            r = await session.execute(select(Student))
            all_s = r.scalars().all()
        for s in all_s:
            if s.tg_id == TEACHER_ID: continue
            un = (s.username or "").lower()
            nm = s.full_name.lower()
            if low == un or low in nm:
                tg = s.tg_id
                break
    if tg is None:
        await message.answer("Не нашёл.")
        return
    
    # ЛОГИКА ОТПРАВКИ В ЗАВИСИМОСТИ ОТ РЕЖИМА
    if mode == "after":
        text = text_pay_after_button()
        kb = paid_button_keyboard()
    else:
        text = "💳 <b>Оплата абонемента</b>\n\nПожалуйста, переведите сумму и отправьте скриншот чека."
        kb = subscription_payment_keyboard()

    try:
        await bot.send_message(tg, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await state.clear()
        return
    await state.clear()
    await message.answer("✅ Отправлено.", reply_markup=back_to_main("menu:pay"))


@dp.callback_query(lambda c: c.data == "paid:send_screenshot")
async def cb_paid_screenshot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Пожалуйста, отправьте фото или скриншот чека прямо в этот чат:")
    await state.set_state(PaymentProof.waiting_photo)

@dp.message(PaymentProof.waiting_photo)
async def process_payment_proof(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фото (скриншот чека).")
        return
    
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == message.from_user.id))
        st = r.scalar_one_or_none()
        if st:
            # Пересылаем чек тебе
            await bot.forward_message(chat_id=TEACHER_ID, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(TEACHER_ID, f"💰 Ученик {st.full_name} прислал(а) скриншот оплаты!")

    await message.answer("✅ Скриншот отправлен преподавателю! Ожидайте подтверждения.", reply_markup=back_to_main())
    await state.clear()

@dp.callback_query(lambda c: c.data == "sp:open")
async def cb_sp_open(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))
        students = r.scalars().all()
    if not students:
        await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
        return
    await callback.message.edit_text("💰 Добавить абонемент\n\nВыбери ученика:", reply_markup=set_paid_students_keyboard(students))

@dp.callback_query(lambda c: c.data.startswith("sp:"))
async def cb_set_paid(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    if callback.data == "sp:open": return await cb_sp_open(callback)
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = await session.get(Student, sid)
    if not student: return
    paid = student.paid_lessons or 0
    text = f"💰 {student.full_name}\n\nСейчас оплачено: {paid}\n\nВыбери новое количество:"
    kb = set_paid_amounts_keyboard(sid, paid)
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("spa:"))
async def cb_set_paid_amount(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    parts = callback.data.split(":")
    sid, amount = int(parts[1]), int(parts[2])
    if amount < 0: amount = 0
    async with async_session() as session:
        student = await session.get(Student, sid)
        if not student: return
        student.paid_lessons = amount
        student.last_payment_reminder = None
        await session.commit()
    paid = student.paid_lessons or 0
    text = f"💰 {student.full_name}\n\nСейчас оплачено: {paid}\n\nВыбери новое количество:"
    kb = set_paid_amounts_keyboard(sid, paid)
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(callback: CallbackQuery):
    await callback.answer("Уведомление отправлено!", show_alert=True)
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))
        st = r.scalar_one_or_none()
        if st:
            await bot.send_message(TEACHER_ID, f"💰 Ученик {st.full_name} (@{st.username}) нажал 'Я оплатил(а)'!")

@dp.callback_query(lambda c: c.data == "ignore")
async def cb_ignore(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    uid = callback.from_user.id
    kb = main_menu_teacher() if is_teacher(uid) else main_menu_student()
    await callback.message.edit_text("Главное меню:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(text_help(), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r = await session.execute(select(Lesson).order_by(Lesson.datetime_start))
        lessons = r.scalars().all()
        r2 = await session.execute(select(Student))
        students = r2.scalars().all()
        s_map = {s.id: s.full_name for s in students}
    if not lessons:
        await callback.message.edit_text("📋 Занятий нет.", reply_markup=back_to_main())
        return
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    past = [l for l in lessons if l.datetime_start < now]
    lines = []
    if future:
        lines.append("📅 Предстоящие:\n")
        for les in future[:20]:
            n = s_map.get(les.student_id, "?")
            s = les.datetime_start.strftime("%d.%m %H:%M")
            lines.append(f"• {s} — {n}")
    if past:
        lines.append("\n✓ Прошедшие:\n")
        for les in past[-10:]:
            n = s_map.get(les.student_id, "?")
            s = les.datetime_start.strftime("%d.%m %H:%M")
            lines.append(f"✓ {s} — {n}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r = await session.execute(select(Lesson).order_by(Lesson.datetime_start))
        lessons = r.scalars().all()
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    if not future:
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        return
    await callback.message.edit_text("🗑 Удалить занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "del"))

@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
    if not lesson: return
    dt = lesson.datetime_start
    text = f"Удалить занятие?\n\n{dt.strftime('%d.%m.%Y %H:%M')}\n{lesson.title}"
    await callback.message.edit_text(text, reply_markup=confirm_delete_keyboard(lid))

@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        if lesson:
            await session.delete(lesson)
            await session.commit()
    await callback.message.edit_text("✅ Удалено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r = await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))
        students = r.scalars().all()
    if not students:
        await callback.message.edit_text("Учеников нет.", reply_markup=back_to_main())
        return
    lines = ["👥 Ученики:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    text = "🔍 Поиск ученика\n\nНапиши @username или имя:"
    await callback.message.edit_text(text, reply_markup=back_to_main())
    await state.set_state(FindStudent.query)

@dp.message(FindStudent.query)
async def find_query(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    q_in = message.text.strip()
    low = q_in.lower().lstrip("@")
    async with async_session() as session:
        r = await session.execute(select(Student))
        all_s = r.scalars().all()
    found = [s for s in all_s if s.tg_id != TEACHER_ID and (low in s.full_name.lower() or low == (s.username or "").lower())]
    if not found:
        await message.answer("❌ Не найден.", reply_markup=back_to_main())
        await state.clear()
        return
    s = found[0]
    paid = s.paid_lessons or 0
    text = f"👤 {s.full_name}\n\n@{s.username or '—'}\nID: {s.tg_id}\n\nОплачено: {paid}"
    await message.answer(text, reply_markup=card_keyboard(s.id))
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu:reschedule")
async def cb_reschedule(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        r = await session.execute(select(Lesson).order_by(Lesson.datetime_start))
        lessons = r.scalars().all()
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    if not future:
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        return
    await callback.message.edit_text("🔄 Перенести занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "resch"))

@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    lid = int(callback.data.split(":")[1])
    await state.update_data(lid=lid)
    await callback.message.edit_text("Введи новую дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(RescheduleFlow.dt)

@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    try:
        new_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
    data = await state.get_data()
    lid = data.get("lid")
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        if lesson:
            lesson.datetime_start = new_dt
            await session.commit()
    await message.answer("✅ Перенесено!", reply_markup=main_menu_teacher())
    await state.clear()


# ---------- WEBHOOK ----------
async def health(request):
    return web.Response(text="OK")

async def on_startup(bot: Bot) -> None:
    print("--- НАЧАЛО ЗАПУСКА БОТА ---")
    try:
        await init_db()
        print("--- БАЗА ДАННЫХ УСПЕШНО ПОДКЛЮЧЕНА ---")
    except Exception as e:
        print(f"!!! ОШИБКА БАЗЫ ДАННЫХ: {e}")
        
    try:
        url = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"
        print(f"--- УСТАНАВЛИВАЮ ВЕБХУК НА: {url} ---")
        await bot.set_webhook(url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True, allowed_updates=["message", "callback_query"])
        print("--- ВЕБХУК УСПЕШНО УСТАНОВЛЕН ---")
    except Exception as e:
        print(f"!!! ОШИБКА ВЕБХУКА: {e}")
        
    try:
        start_scheduler(bot)
        print("--- ПЛАНИРОВЩИК ЗАПУЩЕН ---")
    except Exception as e:
        print(f"!!! ОШИБКА ПЛАНИРОВЩИКА: {e}")

app = web.Application()
handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
handler.register(app, path=WEBHOOK_PATH)
app.router.add_get("/health", health)
setup_application(app, dp, bot=bot)
dp.startup.register(on_startup)

if __name__ == "__main__":
    print("СЕРВЕР aiohttp ЗАПУЩЕН")
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)