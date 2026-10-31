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
from models import Student, Lesson, Homework, HomeworkDone, LessonSlot, HomeworkSubmission
from scheduler import start_scheduler, now_msk
from texts import text_help, text_welcome, text_hw_add_deadline, text_pay_after_button, text_pay_end_button
from keyboards import *

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
    await state.clear()
    user = message.from_user
    is_new = False
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == user.id))).scalar_one_or_none()
        if not student:
            is_new = True
            session.add(Student(tg_id=user.id, full_name=user.full_name, username=user.username))
            await session.commit()
            if user.id != TEACHER_ID:
                try: await bot.send_message(TEACHER_ID, f"🆕 Новый ученик!\n\n{user.full_name}\n@{user.username or '—'}\nID: {user.id}")
                except Exception: pass
    if is_new and not is_teacher(user.id):
        await message.answer("Выбери свой часовой пояс:", reply_markup=timezone_offset_keyboard())
        await state.set_state(SetTimezone.choosing_tz)
    else:
        kb = main_menu_teacher() if is_teacher(user.id) else main_menu_student()
        await message.answer(f"👋 Привет, {user.full_name}!\n\nВыбери действие:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("tz:"), SetTimezone.choosing_tz)
async def cb_set_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data.split(":")[1] == "other": return await callback.message.edit_text("Напиши, на сколько часов твое время отличается от Москвы:")
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if student: student.timezone_offset = int(callback.data.split(":")[1]); await session.commit()
    await callback.message.edit_text("✅ Часовой пояс установлен!")
    await callback.message.answer(text_welcome(), reply_markup=main_menu_student())
    await state.clear()

@dp.message(SetTimezone.choosing_tz)
async def set_tz_text(message: types.Message, state: FSMContext):
    try: offset = int(message.text.strip())
    except ValueError: return await message.answer("Пожалуйста, напиши просто число:")
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == message.from_user.id))).scalar_one_or_none()
        if student: student.timezone_offset = offset; await session.commit()
    await message.answer("✅ Часовой пояс установлен!")
    await message.answer(text_welcome(), reply_markup=main_menu_student())
    await state.clear()

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu_teacher() if is_teacher(message.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:calendar")
async def cb_calendar(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    now = now_msk()
    async with async_session() as session:
        lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= datetime(now.year, now.month, 1)))).scalars().all()
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=calendar_keyboard(now.year, now.month, {l.datetime_start.day for l in lessons if l.datetime_start.month == now.month}, {s.datetime_start.day for s in slots if s.datetime_start.month == now.month}))

@dp.callback_query(lambda c: c.data.startswith("cal:init:"))
async def cb_calendar_init(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    y, m = int(callback.data.split(":")[2]), int(callback.data.split(":")[3])
    async with async_session() as session:
        lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= datetime(y, m, 1)))).scalars().all()
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=calendar_keyboard(y, m, {l.datetime_start.day for l in lessons if l.datetime_start.month == m}, {s.datetime_start.day for s in slots if s.datetime_start.month == m}))

@dp.callback_query(lambda c: c.data == "cal:ignore")
async def cb_cal_ignore(callback: CallbackQuery): await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:day:"))
async def cb_cal_day(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    y, m, d = map(int, callback.data.split(":")[2].split("-"))
    dt_s, dt_e = datetime(y, m, d, 0, 0), datetime(y, m, d, 23, 59)
    async with async_session() as session:
        lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= dt_s, Lesson.datetime_start <= dt_e).order_by(Lesson.datetime_start))).scalars().all()
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.datetime_start >= dt_s, LessonSlot.datetime_start <= dt_e, LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    lines = [f"📅 {d}.{m:02d}.{y}\n"]
    if lessons:
        lines.append("Занятия:")
        for l in lessons: lines.append(f"• {l.datetime_start.strftime('%H:%M')} — {l.title}")
        lines.append("")
    if slots:
        lines.append("Свободные слоты:")
        for s in slots: lines.append(f"🟢 {s.datetime_start.strftime('%H:%M')}")
    if not lines[1:]: lines.append("Занятий нет.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:calendar"))

@dp.callback_query(lambda c: c.data == "menu:slots")
async def cb_slots_menu(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("📅 Слоты:", reply_markup=slots_menu_teacher())

@dp.callback_query(lambda c: c.data == "slot:show_calendar")
async def cb_slot_show_calendar(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    now = now_msk()
    async with async_session() as session:
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await callback.message.edit_text("📅 Выбери день:", reply_markup=calendar_keyboard(now.year, now.month, set(), {s.datetime_start.day for s in slots if s.datetime_start.month == now.month}, prefix="slot"))

@dp.callback_query(lambda c: c.data.startswith("slot:day:"))
async def cb_slot_day(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    y, m, d = map(int, callback.data.split(":")[2].split("-"))
    await state.update_data(date_str=datetime(y, m, d).strftime("%Y-%m-%d"), selected_times=[])
    await callback.message.edit_text(f"📅 {d}.{m:02d}.{y}\n\nВыбери время:", reply_markup=time_picker_keyboard())

@dp.callback_query(lambda c: c.data.startswith("slot:init:"))
async def cb_slot_init(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    y, m = int(callback.data.split(":")[2]), int(callback.data.split(":")[3])
    async with async_session() as session:
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await callback.message.edit_text("📅 Выбери день:", reply_markup=calendar_keyboard(y, m, set(), {s.datetime_start.day for s in slots if s.datetime_start.month == m}, prefix="slot"))

@dp.callback_query(lambda c: c.data.startswith("time:"))
async def cb_time_pick(callback: CallbackQuery, state: FSMContext):
    t_str = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if not data.get("date_str"): return await callback.answer("❌ Ошибка даты.", show_alert=True)
    if t_str == "save":
        selected = data.get("selected_times", [])
        if not selected: return await callback.answer("Ты не выбрал время!", show_alert=True)
        async with async_session() as session:
            for t in selected: session.add(LessonSlot(teacher_id=TEACHER_ID, datetime_start=datetime.strptime(f"{data['date_str']} {t}", "%Y-%m-%d %H:%M")))
            await session.commit()
        await callback.message.edit_text(f"✅ Открыто слотов: {len(selected)}", reply_markup=slots_menu_teacher())
        await state.clear()
        return await callback.answer()
    sel = data.get("selected_times", [])
    if t_str in sel: sel.remove(t_str)
    else: sel.append(t_str)
    await state.update_data(selected_times=sel)
    await callback.message.edit_reply_markup(reply_markup=time_picker_keyboard(set(sel)))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "slot:list")
async def cb_slot_list(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.teacher_id == TEACHER_ID, LessonSlot.is_booked == False, LessonSlot.datetime_start >= now_msk()).order_by(LessonSlot.datetime_start))).scalars().all()
    if not slots: return await callback.message.edit_text("Нет свободных слотов.", reply_markup=slots_menu_teacher())
    await callback.message.edit_text("📅 <b>Твои слоты:</b>\n\nНажми ❌, чтобы закрыть:", reply_markup=slots_delete_keyboard(slots))

@dp.callback_query(lambda c: c.data.startswith("slot:del:"))
async def cb_slot_del(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        slot = await session.get(LessonSlot, int(callback.data.split(":")[2]))
        if slot and not slot.is_booked:
            await session.delete(slot)
            await session.commit()
            await callback.message.answer("✅ Слот закрыт.")
    await cb_slot_list(callback)

@dp.callback_query(lambda c: c.data == "menu:stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        st_cnt = len((await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all())
        ls_cnt = len((await session.execute(select(Lesson))).scalars().all())
        fut_cnt = len((await session.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()))).scalars().all())
        sl_cnt = len((await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False, LessonSlot.datetime_start >= now_msk()))).scalars().all())
    await callback.message.edit_text(f"📊 <b>Статистика</b>\n\n👥 Учеников: {st_cnt}\n📚 Занятий: {ls_cnt}\n📅 Предстоящих: {fut_cnt}\n🟢 Слотов: {sl_cnt}", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
    lines, data = ["👥 Выбери ученика:\n"], {"total": len(students)}
    for i, s in enumerate(students, 1): lines.append(f"{i}. {s.full_name} @{s.username or '—'}"); data[f"s_{i}"] = s.id
    await callback.message.edit_text("\n".join(lines) + f"\n\nНомер 1–{len(students)}", reply_markup=back_to_main())
    await state.update_data(**data); await state.set_state(AddLesson.student)

@dp.message(AddLesson.student)
async def add_student(message: types.Message, state: FSMContext):
    data, txt = await state.get_data(), message.text.strip()
    sid = data.get(f"s_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if sid is None:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            for s in (await session.execute(select(Student))).scalars().all():
                if s.tg_id != TEACHER_ID and (low == (s.username or "").lower() or low in s.full_name.lower()): sid = s.id; break
    if sid is None: return await message.answer("Не нашёл.")
    async with async_session() as session:
        student = await session.get(Student, sid)
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    if not student: return await message.answer("Ученик не найден.")
    await state.update_data(sid=student.id, sname=student.full_name)
    if slots: await message.answer("Выбери слот или введи дату:", reply_markup=slots_picker_keyboard(slots, sid))
    else: await message.answer("Введи дату и время (ДД.ММ.ГГГГ ЧЧ:ММ):"); await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("act_slot:"))
async def cb_act_slot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    _, sid, slot_id = callback.data.split(":")
    async with async_session() as session:
        slot, st = await session.get(LessonSlot, int(slot_id)), await session.get(Student, int(sid))
        if not slot or not st: return
        slot.is_booked = True; await session.commit()
        await state.update_data(sid=st.id, sname=st.full_name, dt=slot.datetime_start)
    await callback.message.edit_text("Введи название (или «-»):"); await state.set_state(AddLesson.title)

@dp.callback_query(lambda c: c.data.startswith("act_manual:"))
async def cb_act_manual(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    async with async_session() as session: st = await session.get(Student, int(callback.data.split(":")[1]))
    if st: await state.update_data(sid=st.id, sname=st.full_name); await callback.message.edit_text("Введи дату (ДД.ММ.ГГГГ ЧЧ:ММ):"); await state.set_state(AddLesson.dt)

@dp.message(AddLesson.dt)
async def add_dt(message: types.Message, state: FSMContext):
    try: dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError: return await message.answer("Формат: 15.10.2026 18:30")
    await state.update_data(dt=dt); await message.answer("Название (или «-»):"); await state.set_state(AddLesson.title)

@dp.message(AddLesson.title)
async def add_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip() if message.text.strip() != "-" else "Корейский"
    async with async_session() as session:
        session.add(Lesson(student_id=data["sid"], datetime_start=data["dt"], title=title)); await session.commit()
    await message.answer(f"✅ Добавлено!\nУченик: {data['sname']}\nДата: {data['dt'].strftime('%d.%m.%Y %H:%M')}", reply_markup=main_menu_teacher())
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu:hw")
async def cb_hw_menu(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("📚 ДЗ", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:create")
async def cb_hw_create(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text("Название темы ДЗ:"); await state.set_state(AddHomework.title)

@dp.message(AddHomework.title)
async def hw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text); await message.answer("Текст задания:"); await state.set_state(AddHomework.text)

@dp.message(AddHomework.text)
async def hw_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text); await message.answer("Прикрепи материал или «-»:"); await state.set_state(AddHomework.media)

@dp.message(AddHomework.media)
async def hw_media(message: types.Message, state: FSMContext):
    m_t, m_i, c_i = ("video", str(message.message_id), message.chat.id) if message.video else ("photo", str(message.message_id), message.chat.id) if message.photo else (None, None, None) if message.text == "-" else (None, None, None)
    if not m_t and message.text != "-": return await message.answer("Пришли видео или «-»:")
    await state.update_data(m_type=m_t, m_id=m_i, c_id=c_i); await message.answer(text_hw_add_deadline()); await state.set_state(AddHomework.deadline)

@dp.message(AddHomework.deadline)
async def hw_deadline(message: types.Message, state: FSMContext):
    data, txt = await state.get_data(), message.text.strip()
    deadline = None
    if txt != "-":
        try: deadline = datetime.strptime(txt, "%d.%m.%Y")
        except ValueError: return await message.answer("Неверный формат.")
    async with async_session() as session:
        session.add(Homework(title=data["title"], text=data["text"], media_type=data.get("m_type"), media_id=data.get("m_id"), chat_id=data.get("c_id"), deadline=deadline)); await session.commit()
    await message.answer("✅ ДЗ создано!", reply_markup=main_menu_teacher()); await state.clear()
@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Как хочешь перенести?", reply_markup=student_transfer_menu())

@dp.callback_query(lambda c: c.data == "transfer:ask_teacher")
async def cb_transfer_ask_teacher(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(f"Напишите преподавателю напрямую:\n👉 {TEACHER_LINK}", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "transfer:ask_slot")
async def cb_transfer_ask_slot(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    if not slots: return await callback.message.edit_text("Свободных слотов нет.", reply_markup=back_to_main())
    b = [[InlineKeyboardButton(text=s.datetime_start.strftime("%d.%m %H:%M"), callback_data=f"transfer:pick:{s.id}")] for s in slots[:10]]
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:main")])
    await callback.message.edit_text("Выбери время:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("transfer:pick:"))
async def cb_transfer_pick(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        slot = await session.get(LessonSlot, int(callback.data.split(":")[2]))
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if not st or not slot: return
        lesson = (await session.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().first()
        if not lesson: return await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"transfer:approve:{lesson.id}:{slot.id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"transfer:decline:{slot.id}:{st.tg_id}")]])
        await bot.send_message(TEACHER_ID, f"🔄 Перенос\nУченик: {st.full_name}\nТекущее: {lesson.datetime_start.strftime('%d.%m %H:%M')}\nХочет: {slot.datetime_start.strftime('%d.%m %H:%M')}", reply_markup=kb)
        slot.is_booked = True
        await session.commit()
    await callback.message.edit_text("✅ Запрос отправлен.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data.startswith("transfer:approve:"))
async def cb_transfer_approve(callback: CallbackQuery):
    await callback.answer("Подтверждено")
    if not is_teacher(callback.from_user.id): return
    _, _, lid, sid = callback.data.split(":")
    async with async_session() as session:
        lesson, slot = await session.get(Lesson, int(lid)), await session.get(LessonSlot, int(sid))
        if lesson and slot:
            lesson.datetime_start = slot.datetime_start
            await session.delete(slot)
            await session.commit()
            await callback.message.edit_text("✅ Перенесено.")
            st = (await session.execute(select(Student).where(Student.id == lesson.student_id))).scalar_one_or_none()
            if st: await bot.send_message(st.tg_id, f"✅ Преподаватель подтвердил перенос!\nНовое время: {lesson.datetime_start.strftime('%d.%m %H:%M')}")

@dp.callback_query(lambda c: c.data.startswith("transfer:decline:"))
async def cb_transfer_decline(callback: CallbackQuery):
    await callback.answer("Отклонено")
    if not is_teacher(callback.from_user.id): return
    parts = callback.data.split(":")
    slot_id = int(parts[2])
    student_tg_id = int(parts[3]) if len(parts) > 3 else None
    async with async_session() as session:
        slot = await session.get(LessonSlot, slot_id)
        if slot:
            slot.is_booked = False
            await session.commit()
    await callback.message.edit_text("❌ Вы отклонили перенос. Слот снова свободен.")
    if student_tg_id:
        try: await bot.send_message(student_tg_id, "❌ Преподаватель не может согласовать это время. Скоро свяжусь с вами.")
        except Exception: pass

@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("💰 Оплата", reply_markup=pay_menu())

@dp.callback_query(lambda c: c.data.startswith("pay:"))
async def cb_pay_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data in ["pay:show_tariffs", "pay:single:req", "pay:back"]: return
    if not is_teacher(callback.from_user.id): return
    mode = callback.data.split(":")[1]
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main("menu:pay"))
    lines, data = ["👥 Кому:\n"], {"mode": mode, "total": len(students)}
    for i, s in enumerate(students, 1): lines.append(f"{i}. {s.full_name} @{s.username or '—'}"); data[f"st_{i}"] = s.tg_id
    await state.update_data(**data); await state.set_state(PayFlow.choosing_student)
    await callback.message.edit_text("\n".join(lines) + f"\n\nНомер 1–{len(students)} или @username:", reply_markup=back_to_main("menu:pay"))

@dp.message(PayFlow.choosing_student)
async def pay_send(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    data, txt = await state.get_data(), message.text.strip()
    tg = data.get(f"st_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if tg is None:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            for s in (await session.execute(select(Student))).scalars().all():
                if s.tg_id != TEACHER_ID and (low == (s.username or "").lower() or low in s.full_name.lower()): tg = s.tg_id; break
    if tg is None: return await message.answer("Не нашёл.")
    if data.get("mode") == "after":
        text = text_pay_after_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", callback_data="pay:single:req")], [InlineKeyboardButton(text="📚 Посмотреть тарифы", callback_data="pay:show_tariffs:single")]])
    else:
        text = text_pay_end_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Выбрать абонемент", callback_data="pay:show_tariffs:sub")]])
    try: await bot.send_message(tg, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e: await message.answer(f"Ошибка: {e}")
    await state.clear(); await message.answer("✅ Отправлено.", reply_markup=back_to_main("menu:pay"))

@dp.callback_query(lambda c: c.data.startswith("pay:show_tariffs"))
async def cb_pay_show_tariffs(callback: CallbackQuery):
    await callback.answer()
    context = callback.data.split(":")[2] if len(callback.data.split(":")) > 2 else "single"
    text = "📚 <b>Наши тарифы:</b>\n\n• Индивидуально (4 занятия) — 4000 ₽\n• Индивидуально (8 занятий) — 7000 ₽\n• В группе (4 занятия) — 2000 ₽\n• В группе (8 занятий) — 3500 ₽\n\nВыберите 👇"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Индивид. 4 зан.", callback_data=f"tar:ind_4:{context}")], [InlineKeyboardButton(text="Индивид. 8 зан.", callback_data=f"tar:ind_8:{context}")], [InlineKeyboardButton(text="Группа 4 зан.", callback_data=f"tar:grp_4:{context}")], [InlineKeyboardButton(text="Группа 8 зан.", callback_data=f"tar:grp_8:{context}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:back:{context}", icon_custom_emoji_id=E_BACK)]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("pay:back:"))
async def cb_pay_back(callback: CallbackQuery):
    await callback.answer()
    context = callback.data.split(":")[2]
    if context == "single":
        text = text_pay_after_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", callback_data="pay:single:req")], [InlineKeyboardButton(text="📚 Посмотреть тарифы", callback_data="pay:show_tariffs:single")]])
    else:
        text = text_pay_end_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Выбрать абонемент", callback_data="pay:show_tariffs:sub")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("tar:"))
async def cb_tariff_chosen(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    context = parts[2] if len(parts) > 2 else "single"
    price = {"ind_4": "4000 ₽", "ind_8": "7000 ₽", "grp_4": "2000 ₽", "grp_8": "3500 ₽"}.get(parts[1], "Уточняйте")
    text = f"Вы выбрали: <b>{price}</b>\n\n<b>Реквизиты:</b>\nЯндекс Банк: <code>+7 927 217-38-06</code>\n\nОтправьте скриншот."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:show_tariffs:{context}", icon_custom_emoji_id=E_BACK)]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "pay:single:req")
async def cb_pay_single_req(callback: CallbackQuery):
    await callback.answer()
    text = f"<b>Разовое занятие</b>\n\nСтоимость: <b>1500 ₽</b>\n\n<b>Реквизиты:</b>\nЯндекс Банк: <code>+7 927 217-38-06</code>\n\nОтправьте скриншот."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="pay:back:single", icon_custom_emoji_id=E_BACK)]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "paid:send_screenshot")
async def cb_paid_screenshot(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text("Отправьте скриншот:"); await state.set_state(PaymentProof.waiting_photo)
@dp.message(PaymentProof.waiting_photo)
async def process_payment_proof(message: types.Message, state: FSMContext):
    if not message.photo: return await message.answer("Нужно фото.")
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == message.from_user.id))).scalar_one_or_none()
        if st:
            await bot.forward_message(chat_id=TEACHER_ID, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(TEACHER_ID, f"💰 {st.full_name} прислал скрин!")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data="paid:click")]])
    await message.answer("✅ Скриншот отправлен! Нажмите кнопку ниже.", reply_markup=kb); await state.clear()

@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(callback: CallbackQuery):
    await callback.answer("ОК", show_alert=True)
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if st: await bot.send_message(TEACHER_ID, f"💰 {st.full_name} (@{st.username}) нажал 'Оплатил'!")
    await callback.message.edit_text("✅ Преподаватель уведомлен!", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "sp:open")
async def cb_sp_open(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
    await callback.message.edit_text("💰 Абонемент:", reply_markup=set_paid_students_keyboard(students))

@dp.callback_query(lambda c: c.data.startswith("sp:"))
async def cb_set_paid(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    if callback.data == "sp:open": return await cb_sp_open(callback)
    async with async_session() as session: student = await session.get(Student, int(callback.data.split(":")[1]))
    if student: await callback.message.edit_text(f"💰 {student.full_name}\nОплачено: {student.paid_lessons or 0}\n\nВыбери:", reply_markup=set_paid_amounts_keyboard(student.id, student.paid_lessons or 0))

@dp.callback_query(lambda c: c.data.startswith("spa:"))
async def cb_set_paid_amount(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    _, sid, amount = callback.data.split(":")
    async with async_session() as session:
        student = await session.get(Student, int(sid))
        if student:
            student.paid_lessons = max(0, int(amount)); await session.commit()
            await callback.message.edit_text(f"💰 {student.full_name}\nОплачено: {student.paid_lessons}\n\nВыбери:", reply_markup=set_paid_amounts_keyboard(student.id, student.paid_lessons))

@dp.callback_query(lambda c: c.data == "ignore")
async def cb_ignore(callback: CallbackQuery): await callback.answer()

@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await callback.answer()
    await callback.message.edit_text("Меню:", reply_markup=main_menu_teacher() if is_teacher(callback.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    await callback.answer(); await callback.message.edit_text(text_help(), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        lessons = (await session.execute(select(Lesson).order_by(Lesson.datetime_start))).scalars().all()
        s_map = {s.id: s.full_name for s in (await session.execute(select(Student))).scalars().all()}
    if not lessons: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    lines = []
    for title, group in [("📅 Предстоящие:", [l for l in lessons if l.datetime_start >= now_msk()]), ("\n✓ Прошедшие:", [l for l in lessons if l.datetime_start < now_msk()][-10:])]:
        if group:
            lines.append(title)
            for les in group: lines.append(f"• {les.datetime_start.strftime('%d.%m %H:%M')} — {s_map.get(les.student_id, '?')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not lessons: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    await callback.message.edit_text("🗑 Удалить:", reply_markup=lessons_action_keyboard(lessons, "del"))

@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lesson = await session.get(Lesson, int(callback.data.split(":")[1]))
    if lesson: await callback.message.edit_text(f"Удалить?", reply_markup=confirm_delete_keyboard(lesson.id))

@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        lesson = await session.get(Lesson, int(callback.data.split(":")[1]))
        if lesson: await session.delete(lesson); await session.commit()
    await callback.message.edit_text("✅ Удалено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    await callback.message.edit_text("👥 Ученики:\n" + "\n".join([f"{i}. {s.full_name} @{s.username or '—'}" for i, s in enumerate(students, 1)]), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await callback.message.edit_text("🔍 Поиск:", reply_markup=back_to_main()); await state.set_state(FindStudent.query)

@dp.message(FindStudent.query)
async def find_query(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    low = message.text.strip().lower().lstrip("@")
    async with async_session() as session: all_s = (await session.execute(select(Student))).scalars().all()
    found = [s for s in all_s if s.tg_id != TEACHER_ID and (low in s.full_name.lower() or low == (s.username or "").lower())]
    if not found: return await message.answer("❌ Нет.", reply_markup=back_to_main()); await state.clear()
    s = found[0]
    await message.answer(f"👤 {s.full_name}\n@{s.username or '—'}\nID: {s.tg_id}\nОплачено: {s.paid_lessons or 0}", reply_markup=card_keyboard(s.id)); await state.clear()

@dp.callback_query(lambda c: c.data == "menu:reschedule")
async def cb_reschedule(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not lessons: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    await callback.message.edit_text("🔄 Перенести:", reply_markup=lessons_action_keyboard(lessons, "resch"))

@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await state.update_data(lid=int(callback.data.split(":")[1]))
    await callback.message.edit_text("Введи дату (ДД.ММ.ГГГГ ЧЧ:ММ):"); await state.set_state(RescheduleFlow.dt)

@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    try: new_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError: return await message.answer("Формат: 15.10.2026 18:30")
    async with async_session() as session:
        lesson = await session.get(Lesson, (await state.get_data()).get("lid"))
        if lesson: lesson.datetime_start = new_dt; await session.commit()
    await message.answer("✅ Перенесено!", reply_markup=main_menu_teacher()); await state.clear()

async def health(request): return web.Response(text="OK")

async def on_startup(bot: Bot) -> None:
    await init_db()
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET, drop_pending_updates=True, allowed_updates=["message", "callback_query"])
    start_scheduler(bot)

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path=WEBHOOK_PATH)
app.router.add_get("/health", health)
setup_application(app, dp, bot=bot)
dp.startup.register(on_startup)

if __name__ == "__main__":
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)