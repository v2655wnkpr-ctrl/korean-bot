import logging
import os
from datetime import datetime

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
    time_picker_keyboard, slots_picker_keyboard, E_ADD, E_LIST, E_DELETE
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = 803167669

if not BOT_TOKEN:
    msg = "Не найден BOT_TOKEN"
    raise ValueError(msg)

logging.basicConfig(level=logging.INFO)

BASE_WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL", "https://localhost")
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

class AddSlot(StatesGroup):
    dt = State()

class SetTimezone(StatesGroup):
    choosing_tz = State()

class PayFlow(StatesGroup):
    choosing_student = State()

class FindStudent(StatesGroup):
    query = State()

class RescheduleFlow(StatesGroup):
    dt = State()

class PaymentProof(StatesGroup):
    waiting_photo = State()

class TransferFlow(StatesGroup):
    reason = State()

class AddHomework(StatesGroup):
    title = State()
    text = State()
    media = State()
    deadline = State()

class SubmitHW(StatesGroup):
    media = State()


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
    await callback.answer()
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
    if not is_teacher(callback.from_user.id):
        return
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
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:init:"))
async def cb_calendar_init(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
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
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cal:ignore")
async def cb_cal_ignore(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:day:"))
async def cb_cal_day(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
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
    await callback.answer()


# ---------- СЛОТЫ ----------

@dp.callback_query(lambda c: c.data == "menu:slots")
async def cb_slots_menu(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    await callback.message.edit_text("📅 Управление слотами", reply_markup=slots_menu_teacher())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "slot:add")
async def cb_slot_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи дату слота (ДД.ММ.ГГГГ):")
    await state.set_state(AddSlot.dt)
    await callback.answer()

@dp.message(AddSlot.dt)
async def process_slot_date(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("Формат: 15.10.2026")
        return
        
    await state.update_data(date_str=dt.strftime("%Y-%m-%d"), selected_times=[])
    await message.answer("Выбери время для слота (можно несколько):", reply_markup=time_picker_keyboard())

@dp.callback_query(lambda c: c.data.startswith("time:"))
async def cb_time_pick(callback: CallbackQuery, state: FSMContext):
    time_str = callback.data.split(":")[1]
    data = await state.get_data()
    date_str = data.get("date_str")
    
    if not date_str:
        await callback.message.edit_text("❌ Ошибка: дата не найдена. Попробуй заново.")
        await state.clear()
        await callback.answer()
        return

    if time_str == "save":
        selected = data.get("selected_times", [])
        if not selected:
            await callback.answer("Ты не выбрал ни одного времени!")
            return
            
        async with async_session() as session:
            for t in selected:
                dt = datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M")
                slot = LessonSlot(teacher_id=TEACHER_ID, datetime_start=dt)
                session.add(slot)
            await session.commit()
            
        await callback.message.edit_text(f"✅ Открыто слотов: {len(selected)}", reply_markup=main_menu_teacher())
        await state.clear()
        await callback.answer()
        return

    selected = data.get("selected_times", [])
    if time_str in selected:
        selected.remove(time_str)
    else:
        selected.append(time_str)
        
    await state.update_data(selected_times=selected)
    
    await callback.message.edit_reply_markup(
        reply_markup=time_picker_keyboard(set(selected))
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "slot:list")
async def cb_slot_list(callback: CallbackQuery):
    now = now_msk()
    async with async_session() as session:
        q = select(LessonSlot).where(
            LessonSlot.teacher_id == TEACHER_ID,
            LessonSlot.is_booked == False,
            LessonSlot.datetime_start >= now
        ).order_by(LessonSlot.datetime_start)
        r = await session.execute(q)
        slots = r.scalars().all()
    if not slots:
        await callback.message.edit_text("Нет свободных слотов.", reply_markup=slots_menu_teacher())
        return
    lines = ["📅 Свободные слоты:\n"]
    for s in slots:
        lines.append(f"• {s.datetime_start.strftime('%d.%m %H:%M')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=slots_menu_teacher())
    await callback.answer()
# ---------- ДОБАВЛЕНИЕ ЗАНЯТИЯ ----------

@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        return
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
        result = await session.execute(q)
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
    await callback.answer()
    
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
        if 1 <= num <= total:
            sid = data.get(f"s_{num}")
    if sid is None:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            q = select(Student)
            r = await session.execute(q)
            all_s = r.scalars().all()
        for s in all_s:
            if s.tg_id == TEACHER_ID:
                continue
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
        q = select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start)
        r = await session.execute(q)
        slots = r.scalars().all()
        
    if slots:
        kb = slots_picker_keyboard(slots, sid)
        await message.answer("Выбери свободный слот или введи дату вручную:", reply_markup=kb)
        return
    
    await message.answer("Введи дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("act_slot:"))
async def cb_act_slot(callback: CallbackQuery, state: FSMContext):
    _, sid_str, slot_id_str = callback.data.split(":")
    sid = int(sid_str)
    slot_id = int(slot_id_str)
    
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        student = await session.get(Student, sid)
        if not slot or not student:
            await callback.answer("Ошибка")
            return
            
        slot.is_booked = True
        await session.commit()
        
        await state.update_data(
            sid=student.id, 
            sname=student.full_name, 
            dt=slot.datetime_start, 
            slot_id=slot.id
        )
        
    await callback.message.edit_text("Введи название занятия (или «-»):")
    await state.set_state(AddLesson.title)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("act_manual:"))
async def cb_act_manual(callback: CallbackQuery, state: FSMContext):
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = await session.get(Student, sid)
        if not student:
            await callback.answer("Ошибка")
            return
        await state.update_data(sid=student.id, sname=student.full_name)
        
    await callback.message.edit_text("Введи дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(AddLesson.dt)
    await callback.answer()

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
    if title == "-":
        title = "Корейский"
        
    async with async_session() as session:
        lesson = Lesson(
            student_id=data["sid"], 
            datetime_start=data["dt"], 
            title=title
        )
        session.add(lesson)
        await session.commit()
        
    dt = data["dt"]
    text = f"✅ Занятие добавлено!\n\nУченик: {data['sname']}\nДата: {dt.strftime('%d.%m.%Y %H:%M')}\nНазвание: {title}"
    await message.answer(text, reply_markup=main_menu_teacher())
    await state.clear()


# ---------- ВСЕ ЗАНЯТИЯ, УДАЛЕНИЕ, ПОИСК, УЧЕНИКИ, ПЕРЕНОС ----------

@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
        q2 = select(Student)
        r2 = await session.execute(q2)
        students = r2.scalars().all()
        s_map = {s.id: s.full_name for s in students}
    if not lessons:
        await callback.message.edit_text("📋 Занятий нет.", reply_markup=back_to_main())
        await callback.answer()
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
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    if not future:
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        await callback.answer()
        return
    await callback.message.edit_text("🗑 Удалить занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "del"))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
    if not lesson:
        return
    dt = lesson.datetime_start
    text = f"Удалить занятие?\n\n{dt.strftime('%d.%m.%Y %H:%M')}\n{lesson.title}"
    await callback.message.edit_text(text, reply_markup=confirm_delete_keyboard(lid))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        if lesson:
            await session.delete(lesson)
            await session.commit()
    await callback.message.edit_text("✅ Удалено.", reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    if not is_teacher(callback.from_user.id):
        return
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
        r = await session.execute(q)
        students = r.scalars().all()
    if not students:
        await callback.message.edit_text("Учеников нет.", reply_markup=back_to_main())
        return
    lines = ["👥 Ученики:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(callback: CallbackQuery, state: FSMContext):
    if not is_teacher(callback.from_user.id):
        return
    text = "🔍 Поиск ученика\n\nНапиши @username или имя:"
    await callback.message.edit_text(text, reply_markup=back_to_main())
    await state.set_state(FindStudent.query)
    await callback.answer()

@dp.message(FindStudent.query)
async def find_query(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id):
        return
    q_in = message.text.strip()
    low = q_in.lower().lstrip("@")
    async with async_session() as session:
        q = select(Student)
        r = await session.execute(q)
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
    if not is_teacher(callback.from_user.id):
        return
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    if not future:
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        return
    await callback.message.edit_text("🔄 Перенести занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "resch"))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(callback: CallbackQuery, state: FSMContext):
    if not is_teacher(callback.from_user.id):
        return
    lid = int(callback.data.split(":")[1])
    await state.update_data(lid=lid)
    await callback.message.edit_text("Введи новую дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await state.set_state(RescheduleFlow.dt)
    await callback.answer()

@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id):
        return
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
    await init_db()
    logging.info("БД готова")
    await bot.set_webhook(
        f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logging.info("Webhook ок")
    start_scheduler(bot)

app = web.Application()
handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
handler.register(app, path=WEBHOOK_PATH)
app.router.add_get("/health", health)
setup_application(app, dp, bot=bot)
dp.startup.register(on_startup)

if __name__ == "__main__":
    print("Сервер запущен")
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)