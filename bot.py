import logging
import os
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from sqlalchemy import select
from database import init_db, async_session
from models import Student, Lesson, LessonSlot, Homework, HomeworkMedia, HomeworkDone
from scheduler import start_scheduler, now_msk
from texts import *
from keyboards import *

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = 803167669 # ID КОРЕЙСКОГО БОТА
if not BOT_TOKEN: raise ValueError("Не найден BOT_TOKEN")
logging.basicConfig(level=logging.INFO)
URL = os.getenv("WEBHOOK_URL", "http://localhost").rstrip("/")
PATH = "/webhook"
SECRET = "my-secret-token"
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8080))
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddLesson(StatesGroup):
    student = State(); dt = State(); title = State()
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
class SetCustomName(StatesGroup):
    waiting_name = State()
class AddHomework(StatesGroup):
    title = State(); text = State(); media = State(); deadline = State()
class EditHW(StatesGroup):
    text = State()
class SubmitHW(StatesGroup):
    media = State()

def is_teacher(uid: int) -> bool: return uid == TEACHER_ID

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user, uid = message.from_user, message.from_user.id
    is_new = False
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == uid))).scalar_one_or_none()
        if not student:
            is_new = True
            session.add(Student(tg_id=uid, full_name=user.full_name, username=user.username))
            await session.commit()
            if uid != TEACHER_ID:
                try: await bot.send_message(TEACHER_ID, f"🆕 Новый ученик!\n\n{user.full_name}\n@{user.username or '—'}")
                except Exception: pass

    if is_teacher(uid):
        await message.answer("👋 Привет, преподаватель!", reply_markup=main_menu_teacher())
    elif is_new:
        await message.answer(text_welcome(), reply_markup=main_menu_student())
        await message.answer("Выбери свой часовой пояс:", reply_markup=timezone_offset_keyboard())
        await state.set_state(SetTimezone.choosing_tz)
    else:
        await message.answer("Главное меню:", reply_markup=main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:timezone")
async def cb_menu_timezone(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Выбери свой часовой пояс:", reply_markup=timezone_offset_keyboard())
    await state.set_state(SetTimezone.choosing_tz)

@dp.callback_query(lambda c: c.data.startswith("tz:"), SetTimezone.choosing_tz)
async def cb_set_tz(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data.split(":")[1] == "other": 
        return await callback.message.edit_text("Напиши, на сколько часов твое время отличается от Москвы (например: 3 или -2):")
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if student: 
            student.timezone_offset = int(callback.data.split(":")[1])
            await session.commit()
    kb = main_menu_teacher() if is_teacher(callback.from_user.id) else main_menu_student()
    await callback.message.edit_text("✅ Часовой пояс установлен!")
    if not is_teacher(callback.from_user.id): await callback.message.answer(text_welcome(), reply_markup=kb)
    await state.clear()

@dp.message(SetTimezone.choosing_tz)
async def set_tz_text(message: types.Message, state: FSMContext):
    try: offset = int(message.text.strip())
    except ValueError: return await message.answer("Напиши число (например: 3 или -2):")
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == message.from_user.id))).scalar_one_or_none()
        if student: 
            student.timezone_offset = offset
            await session.commit()
    kb = main_menu_teacher() if is_teacher(message.from_user.id) else main_menu_student()
    await message.answer("✅ Часовой пояс установлен!")
    if not is_teacher(message.from_user.id): await message.answer(text_welcome(), reply_markup=kb)
    await state.clear()

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
        s_map = {s.id: (s.custom_name or s.full_name) for s in (await session.execute(select(Student))).scalars().all()}
    lines = [f"📅 {d}.{m:02d}.{y}\n"]
    if lessons:
        for l in lessons: lines.append(f"• {l.datetime_start.strftime('%H:%M')} — {s_map.get(l.student_id, '?')} ({l.title})")
    else: lines.append("Занятий нет.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:calendar"))

@dp.callback_query(lambda c: c.data == "menu:slots")
async def cb_slots_menu(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("📅 Управление слотами:", reply_markup=slots_menu_teacher())

@dp.callback_query(lambda c: c.data == "slot:show_calendar")
async def cb_slot_show_calendar(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    now = now_msk()
    async with async_session() as session: slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
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
    async with async_session() as session: slots = (await session.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
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
    async with async_session() as session: slots = (await session.execute(select(LessonSlot).where(LessonSlot.teacher_id == TEACHER_ID, LessonSlot.is_booked == False, LessonSlot.datetime_start >= now_msk()).order_by(LessonSlot.datetime_start))).scalars().all()
    if not slots: return await callback.message.edit_text("Нет свободных слотов.", reply_markup=slots_menu_teacher())
    await callback.message.edit_text("📅 <b>Твои слоты:</b>\n\nНажми ❌, чтобы закрыть:", reply_markup=slots_delete_keyboard(slots))

@dp.callback_query(lambda c: c.data.startswith("slot:del:"))
async def cb_slot_del(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        slot = await session.get(LessonSlot, int(callback.data.split(":")[2]))
        if slot and not slot.is_booked: await session.delete(slot); await session.commit(); await callback.message.answer("✅ Слот закрыт.")
    await cb_slot_list(callback)

@dp.callback_query(lambda c: c.data == "menu:lessons")
async def cb_lessons(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if not student: return
        lessons = (await session.execute(select(Lesson).where(Lesson.student_id == student.id).order_by(Lesson.datetime_start))).scalars().all()
    if not lessons: 
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")]])
        return await callback.message.edit_text("📅 Нет занятий.", reply_markup=kb)
    now = now_msk()
    lines = ["📅 Твои занятия:\n"]
    for les in lessons:
        mark = "✓" if les.datetime_start < now else "•"
        local_dt = les.datetime_start + timedelta(hours=student.timezone_offset)
        lines.append(f"{mark} {local_dt.strftime('%d.%m %H:%M')} — {les.title}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Перенести занятие", callback_data="transfer:click")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")]])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)

@dp.callback_query(lambda c: c.data == "menu:settings")
async def cb_settings(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
    if not student: return await callback.answer("Сначала /start")
    await callback.message.edit_text(f"⚙️ Напоминания\n\nСейчас {hours_text(student.custom_hours_before or 2)}.", reply_markup=hours_keyboard())

@dp.callback_query(lambda c: c.data.startswith("h:"))
async def cb_hours(callback: CallbackQuery):
    await callback.answer()
    hours = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if student: student.custom_hours_before = hours; await session.commit()
    await callback.message.edit_text(f"✅ Готово! Напомню {hours_text(hours)}.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
    lines, data = ["👥 Выбери ученика:\n"], {"total": len(students)}
    for i, s in enumerate(students, 1): lines.append(f"{i}. {s.custom_name or s.full_name} @{s.username or '—'}"); data[f"s_{i}"] = s.id
    await callback.message.edit_text("\n".join(lines) + f"\n\nНомер 1–{len(students)}", reply_markup=back_to_main())
    await state.update_data(**data); await state.set_state(AddLesson.student)

@dp.message(AddLesson.student)
async def add_student(message: types.Message, state: FSMContext):
    data, txt = await state.get_data(), message.text.strip()
    sid = data.get(f"s_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if not sid:
        low = txt.lower().lstrip("@")
        async with async_session() as session:
            for s in (await session.execute(select(Student))).scalars().all():
                if s.tg_id != TEACHER_ID and (low == (s.username or "").lower() or low in s.full_name.lower()): sid = s.id; break
    if not sid: return await message.answer("Не нашёл.")
    
    async with async_session() as session: 
        student = await session.get(Student, sid)
        
    await state.update_data(sid=student.id, sname=(student.custom_name or student.full_name))
    
    now = now_msk()
    kb = calendar_keyboard(now.year, now.month, set(), prefix="actcal")
    kb.inline_keyboard.insert(-1, [InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="actcal:manual")])
    
    await message.answer(
        f"Ученик: {student.custom_name or student.full_name}\n\nВыбери дату в календаре или нажми «Ввести вручную»:", 
        reply_markup=kb
    )
@dp.callback_query(lambda c: c.data.startswith("actcal:init:"))
async def cb_actcal_init(callback: CallbackQuery):
    await callback.answer()
    y, m = int(callback.data.split(":")[2]), int(callback.data.split(":")[3])
    kb = calendar_keyboard(y, m, set(), prefix="actcal")
    kb.inline_keyboard.insert(-1, [InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="actcal:manual")])
    await callback.message.edit_text("📅 Выбери дату:", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("actcal:day:"))
async def cb_actcal_day(callback: CallbackQuery):
    await callback.answer()
    date_str = callback.data.split(":")[2]
    y, m, d = map(int, date_str.split("-"))
    kb = lesson_time_keyboard(date_str)
    await callback.message.edit_text(f"📅 {d}.{m:02d}.{y}\n\nВыбери время:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "actcal:manual")
async def cb_actcal_manual(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Введи дату и время в формате:\nДД.ММ.ГГГГ ЧЧ:ММ")
    await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("actcal:time:"))
async def cb_actcal_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(":")
    date_str = parts[2]
    time_str = parts[3]
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    
    async with async_session() as session:
        if (await session.execute(select(Lesson).where(Lesson.datetime_start == dt))).scalars().first():
            return await callback.message.edit_text("⚠️ На это время уже есть занятие!", reply_markup=back_to_main())
            
    await state.update_data(dt=dt)
    await callback.message.edit_text("Введи название занятия (или «-» для «Корейский язык»):")
    await state.set_state(AddLesson.title)

@dp.message(AddLesson.title)
async def add_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip() if message.text.strip() != "-" else "Корейский"
    async with async_session() as session:
        session.add(Lesson(student_id=data["sid"], datetime_start=data["dt"], title=title))
        await session.commit()
    try: await bot.send_message(TEACHER_ID, f"🆕 Добавлено занятие!\nУченик: {data['sname']}\nДата: {data['dt'].strftime('%d.%m.%Y %H:%M')}")
    except Exception: pass
    await message.answer(f"✅ Добавлено!\n{data['sname']}\n{data['dt'].strftime('%d.%m.%Y %H:%M')}", reply_markup=main_menu_teacher())
    await state.clear()
@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not lessons: return await callback.message.edit_text("Нет предстоящих.", reply_markup=back_to_main())
    await callback.message.edit_text("🗑 Удалить:", reply_markup=lessons_action_keyboard(lessons, "del"))

@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lesson = await session.get(Lesson, int(callback.data.split(":")[1]))
    if lesson: await callback.message.edit_text(f"Удалить?\n{lesson.datetime_start.strftime('%d.%m.%Y %H:%M')}\n{lesson.title}", reply_markup=confirm_delete_keyboard(lesson.id))

@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        lesson = await session.get(Lesson, int(callback.data.split(":")[1]))
        if lesson: await session.delete(lesson); await session.commit()
    await callback.message.edit_text("✅ Удалено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        lessons = (await session.execute(select(Lesson).order_by(Lesson.datetime_start))).scalars().all()
        s_map = {s.id: (s.custom_name or s.full_name) for s in (await session.execute(select(Student))).scalars().all()}
    if not lessons: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    lines = []
    for t, grp in [("📅 Предстоящие:", [l for l in lessons if l.datetime_start >= now_msk()]), ("\n✓ Прошедшие:", [l for l in lessons if l.datetime_start < now_msk()][-10:])]:
        if grp:
            lines.append(t)
            for les in grp: lines.append(f"• {les.datetime_start.strftime('%d.%m %H:%M')} — {s_map.get(les.student_id, '?')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session:
        st_cnt = len((await session.execute(select(Student))).scalars().all())
        ls_cnt = len((await session.execute(select(Lesson))).scalars().all())
    now = now_msk()
    done = len([l for l in (await session.execute(select(Lesson))).scalars().all() if l.datetime_start < now])
    await callback.message.edit_text(f"📊 Статистика:\nУчеников: {st_cnt}\nЗанятий: {ls_cnt}\nПроведено: {done}\nПредстоит: {ls_cnt - done}", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет.", reply_markup=back_to_main())
    await callback.message.edit_text("👥 Ученики:\n" + "\n".join([f"{i}. {s.custom_name or s.full_name} @{s.username or '—'}" for i, s in enumerate(students, 1)]), reply_markup=back_to_main())

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
    await message.answer(f"👤 {s.custom_name or s.full_name}\n@{s.username or '—'}", reply_markup=card_keyboard(s.id)); await state.clear()

@dp.callback_query(lambda c: c.data.startswith("act:add:"))
async def cb_card_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    sid = int(callback.data.split(":")[2])
    async with async_session() as session: student = await session.get(Student, sid)
    await state.update_data(sid=student.id, sname=(student.custom_name or student.full_name))
    await callback.message.edit_text("Введи дату:\nДД.ММ.ГГГГ ЧЧ:ММ"); await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("act:pay:"))
async def cb_card_pay(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: student = await session.get(Student, int(callback.data.split(":")[2]))
    if not student: return
    try: await bot.send_message(student.tg_id, text_pay_after_button(), reply_markup=paid_button_keyboard())
    except Exception as e: return await callback.message.answer(f"Ошибка: {e}")
    await callback.message.edit_text("✅ Отправлено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data.startswith("stdel:ask:"))
async def cb_stdel_ask(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await callback.message.edit_text("Удалить ученика?", reply_markup=confirm_delete_student_keyboard(int(callback.data.split(":")[2])))

@dp.callback_query(lambda c: c.data.startswith("stdel:"))
async def cb_stdel_confirm(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        for l in (await session.execute(select(Lesson).where(Lesson.student_id == sid))).scalars().all(): await session.delete(l)
        student = await session.get(Student, sid)
        if student: await session.delete(student)
        await session.commit()
    await callback.message.edit_text("✅ Удалён.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data.startswith("stdel:setname:"))
async def cb_setname_ask(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    sid = int(callback.data.split(":")[2])
    await state.update_data(sid=sid)
    await callback.message.edit_text("Напиши имя, которое я буду показывать тебе вместо телеграм-ника:\n(например: «Алина Корея»)")
    await state.set_state(SetCustomName.waiting_name)

@dp.message(SetCustomName.waiting_name)
async def save_custom_name(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    data = await state.get_data()
    sid = data.get("sid")
    new_name = message.text.strip()
    async with async_session() as session:
        student = await session.get(Student, sid)
        if student:
            student.custom_name = new_name
            await session.commit()
    await message.answer(f"✅ Готово! Теперь ученик отображается как: <b>{new_name}</b>", reply_markup=main_menu_teacher(), parse_mode="HTML")
    await state.clear()

@dp.callback_query(lambda c: c.data == "menu:reschedule")
async def cb_reschedule(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: lessons = (await session.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not lessons: return await callback.message.edit_text("Нет предстоящих.", reply_markup=back_to_main())
    await callback.message.edit_text("🔄 Перенести:", reply_markup=lessons_action_keyboard(lessons, "resch"))

@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    await state.update_data(lid=int(callback.data.split(":")[1]))
    await callback.message.edit_text("Введи новую дату:\nДД.ММ.ГГГГ ЧЧ:ММ"); await state.set_state(RescheduleFlow.dt)

@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    try: new_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError: return await message.answer("Формат: 15.10.2026 18:30")
    async with async_session() as session:
        lesson = await session.get(Lesson, (await state.get_data()).get("lid"))
        if lesson:
            lesson.datetime_start = new_dt; lesson.is_done = False; await session.commit()
            student = await session.get(Student, lesson.student_id)
            if student:
                try: await bot.send_message(student.tg_id, f"🔄 Занятие перенесено!\nНовое время: {new_dt.strftime('%d.%m %H:%M')}")
                except Exception: pass
    await message.answer("✅ Перенесено!", reply_markup=main_menu_teacher()); await state.clear()

@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(text_transfer_ask(), reply_markup=transfer_cancel_keyboard()); await state.set_state(TransferFlow.reason)

@dp.callback_query(lambda c: c.data == "transfer:cancel")
async def cb_transfer_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text(text_transfer_cancel(), reply_markup=back_to_main()); await state.clear()

@dp.message(TransferFlow.reason)
async def transfer_reason(message: types.Message, state: FSMContext):
    try: await bot.send_message(TEACHER_ID, f"🔄 Запрос на перенос\nУченик: {message.from_user.full_name}\nПричина: {message.text.strip()}")
    except Exception: pass
    await message.answer(text_transfer_sent(), reply_markup=back_to_main()); await state.clear()

@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("💰 Оплата", reply_markup=pay_menu())

@dp.callback_query(lambda c: c.data in ["pay:after", "pay:end"])
async def cb_pay_choose(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    mode = callback.data.split(":")[1]
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    lines, data = ["👥 Кому:\n"], {"mode": mode, "total": len(students)}
    for i, s in enumerate(students, 1): lines.append(f"{i}. {s.custom_name or s.full_name}"); data[f"st_{i}"] = s.tg_id
    await state.update_data(**data); await state.set_state(PayFlow.choosing_student)
    await callback.message.edit_text("\n".join(lines) + f"\nНомер 1–{len(students)}:", reply_markup=back_to_main("menu:pay"))

@dp.message(PayFlow.choosing_student)
async def pay_send(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id): return
    data, txt = await state.get_data(), message.text.strip()
    tg = data.get(f"st_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if tg is None:
        async with async_session() as session:
            for s in (await session.execute(select(Student))).scalars().all():
                if s.tg_id != TEACHER_ID and (txt.lower() == (s.username or "").lower() or txt.lower() in s.full_name.lower()): tg = s.tg_id; break
    if tg is None: return await message.answer("Не нашёл.")
    
    if data.get("mode") == "after":
        text = text_pay_after_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", callback_data="pay:single:req")], [InlineKeyboardButton(text="📚 Посмотреть тарифы", callback_data="pay:show_tariffs:single")]])
    else:
        text = text_pay_end_button()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Выбрать абонемент", callback_data="pay:show_tariffs:sub")]])
    try: await bot.send_message(tg, text, reply_markup=kb)
    except Exception as e: await message.answer(f"Ошибка: {e}")
    await state.clear(); await message.answer("✅ Отправлено.", reply_markup=back_to_main("menu:pay"))

@dp.callback_query(lambda c: c.data.startswith("pay:show_tariffs"))
async def cb_pay_show_tariffs(callback: CallbackQuery):
    await callback.answer()
    context = callback.data.split(":")[2] if len(callback.data.split(":")) > 2 else "single"
    text = text_tariffs()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="4 зан. — 2500₽", callback_data=f"tar:ind_4:{context}")],
        [InlineKeyboardButton(text="8 зан. — 5000₽", callback_data=f"tar:ind_8:{context}")],
        [InlineKeyboardButton(text="4 зан. (группа) — 1500₽", callback_data=f"tar:grp_4:{context}")],
        [InlineKeyboardButton(text="8 зан. (группа) — 3500₽", callback_data=f"tar:grp_8:{context}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:back:{context}")]
    ])
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
    price = {"ind_4": "2500 ₽", "ind_8": "5000 ₽", "grp_4": "1500 ₽", "grp_8": "3500 ₽"}.get(parts[1], "Уточняйте")
    text = f"Вы выбрали: <b>{price}</b>\n\n<b>Реквизиты:</b>\nАльфа Банк: <code>+7 927 217-38-06</code> (Тимур)\n\nВ комментарии укажите: «Оплата услуг»\n\nОтправьте скриншот."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Отправить скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:show_tariffs:{context}")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "pay:single:req")
async def cb_pay_single_req(callback: CallbackQuery):
    await callback.answer()
    text = text_pay_after()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Отправить скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="pay:back:single")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "paid:send_screenshot")
async def cb_paid_screenshot(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text("Отправьте скриншот:", reply_markup=back_from_paid_keyboard()); await state.set_state(PaymentProof.waiting_photo)

@dp.callback_query(lambda c: c.data == "paid:back")
async def cb_paid_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text("Ок, отменено.", reply_markup=back_to_main()); await state.clear()

@dp.message(PaymentProof.waiting_photo)
async def receive_photo(message: types.Message, state: FSMContext):
    if not message.photo: return await message.answer("Нужно фото.")
    try: await bot.send_photo(TEACHER_ID, message.photo[-1].file_id, caption=f"💳 Оплата от {message.from_user.full_name}")
    except Exception: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data="paid:click")]])
    await message.answer("✅ Скриншот отправлен! Теперь нажмите кнопку ниже.", reply_markup=kb); await state.clear()

@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(callback: CallbackQuery):
    await callback.answer("ОК", show_alert=True)
    await bot.send_message(TEACHER_ID, f"💰 {callback.from_user.full_name} нажал 'Оплатил'!")
    await callback.message.edit_text("✅ Преподаватель уведомлен!", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "sp:open")
async def cb_sp_open(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
    await callback.message.edit_text("💰 Отметить оплату:", reply_markup=set_paid_students_keyboard(students))

@dp.callback_query(lambda c: c.data.startswith("sp:"))
async def cb_set_paid(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    if callback.data == "sp:open": return await cb_sp_open(callback)
    async with async_session() as session: student = await session.get(Student, int(callback.data.split(":")[1]))
    if student: await callback.message.edit_text(f"💰 {student.custom_name or student.full_name}\nОплачено: {student.paid_lessons or 0}", reply_markup=set_paid_amounts_keyboard(student.id, student.paid_lessons or 0))

@dp.callback_query(lambda c: c.data.startswith("spa:"))
async def cb_set_paid_amount(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    _, sid, amount = callback.data.split(":")
    async with async_session() as session:
        student = await session.get(Student, int(sid))
        if student:
            student.paid_lessons = max(0, int(amount)); student.last_payment_reminder = None; await session.commit()
            await callback.message.edit_text(f"💰 {student.custom_name or student.full_name}\nОплачено: {student.paid_lessons}", reply_markup=set_paid_amounts_keyboard(student.id, student.paid_lessons))

# --- ДОМАШКИ ---
@dp.callback_query(lambda c: c.data == "menu:hw")
async def cb_hw_menu(callback: CallbackQuery):
    await callback.answer()
    if is_teacher(callback.from_user.id): await callback.message.edit_text("📚 Управление ДЗ", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:create")
async def cb_hw_create(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await callback.message.edit_text("Введи название темы ДЗ:"); await state.set_state(AddHomework.title)

@dp.message(AddHomework.title)
async def hw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text); await message.answer("Введи текст задания (можешь прикрепить фото и текст в одном сообщении):"); await state.set_state(AddHomework.text)

@dp.message(AddHomework.text)
async def hw_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    if message.photo: await state.update_data(media_list=[("photo", message.photo[-1].file_id, message.chat.id)])
    elif message.video: await state.update_data(media_list=[("video", message.video.file_id, message.chat.id)])
    await message.answer("Пришли файлы (можно несколько фото/видео). Если файлов нет — напиши «-»:"); await state.set_state(AddHomework.media)

@dp.message(AddHomework.media)
async def hw_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    media_list = data.get("media_list", [])
    if message.photo: media_list.append(("photo", message.photo[-1].file_id, message.chat.id))
    elif message.video: media_list.append(("video", message.video.file_id, message.chat.id))
    elif message.text == "-": pass
    else: return await message.answer("Пришли фото/видео или «-»:")
    
    await state.update_data(media_list=media_list)
    if message.text == "-":
        await message.answer(text_hw_add_deadline())
        await state.set_state(AddHomework.deadline)
    else: await message.answer("Файл добавлен. Пришли еще или напиши «-», чтобы завершить:")

@dp.message(AddHomework.deadline)
async def hw_deadline(message: types.Message, state: FSMContext):
    data = await state.get_data()
    txt = message.text.strip(); deadline = None
    if txt != "-":
        try: deadline = datetime.strptime(txt, "%d.%m.%Y")
        except ValueError: return await message.answer("Неверный формат. Пример: 25.10.2026 или «-»")
    async with async_session() as session:
        hw = Homework(title=data["title"], text=data.get("text", "Без описания"), target_student_id=None, deadline=deadline)
        session.add(hw); await session.flush()
        for m_type, m_id, c_id in data.get("media_list", []):
            session.add(HomeworkMedia(homework_id=hw.id, media_type=m_type, media_id=m_id, chat_id=c_id))
        await session.commit()
    await message.answer("✅ ДЗ создано и сохранено как «Общее»!", reply_markup=hw_menu_teacher()); await state.clear()

@dp.callback_query(lambda c: c.data == "hw:assign_menu")
async def cb_hw_assign_menu(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    async with async_session() as session: students = (await session.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not students: return await callback.message.edit_text("Нет учеников.", reply_markup=hw_menu_teacher())
    await callback.message.edit_text("👤 Кому назначить ДЗ?", reply_markup=hw_assign_students_kb(students))

@dp.callback_query(lambda c: c.data.startswith("hw:assign_stud:"))
async def cb_hw_assign_stud(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    target = callback.data.split(":")[2]
    async with async_session() as session: hws = (await session.execute(select(Homework).order_by(Homework.id.desc()))).scalars().all()
    if not hws: return await callback.message.edit_text("Сначала создай хотя бы одно ДЗ.", reply_markup=hw_menu_teacher())
    await callback.message.edit_text("📚 Какое ДЗ назначить?", reply_markup=hw_assign_list_kb(hws, target))

@dp.callback_query(lambda c: c.data.startswith("hw:assign_do:"))
async def cb_hw_assign_do(callback: CallbackQuery):
    await callback.answer()
    if not is_teacher(callback.from_user.id): return
    _, _, target, hw_id = callback.data.split(":")
    target_id = None if target == "all" else int(target)
    async with async_session() as session:
        hw = await session.get(Homework, int(hw_id))
        if hw:
            hw.target_student_id = target_id; await session.commit()
            target_name = "Все ученики" if target_id is None else "Ученик"
            if target_id:
                st = await session.get(Student, target_id)
                if st: target_name = st.custom_name or st.full_name
            await callback.message.edit_text(f"✅ ДЗ «{hw.title}» назначено: <b>{target_name}</b>", reply_markup=hw_menu_teacher(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "hw:list_teacher")
async def cb_hw_list_teacher(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session: hws = (await session.execute(select(Homework).order_by(Homework.id.desc()))).scalars().all()
    if not hws: return await callback.message.edit_text("Нет ДЗ.", reply_markup=hw_menu_teacher())
    b = []
    for hw in hws:
        target = "Всем"
        if hw.target_student_id:
            async with async_session() as session:
                st = await session.get(Student, hw.target_student_id)
                if st: target = st.custom_name or st.full_name
        b.append([InlineKeyboardButton(text=f"{hw.created_at.strftime('%d.%m')} — {hw.title} (для {target})", callback_data=f"hw:view_teacher:{hw.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:hw")])
    await callback.message.edit_text("📚 Выбери ДЗ:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:view_teacher:"))
async def cb_hw_view_teacher(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
        if not hw: return
        media = (await session.execute(select(HomeworkMedia).where(HomeworkMedia.homework_id == hw_id))).scalars().all()
    text = f"📚 <b>{hw.title}</b>\n\n{hw.text}"
    if hw.deadline: text += f"\n\n📅 Дедлайн: {hw.deadline.strftime('%d.%m.%Y')}"
    await callback.message.edit_text(text, reply_markup=hw_view_teacher_keyboard(hw.id), parse_mode="HTML")
    for m in media:
        try:
            if m.media_type == "photo": await bot.send_photo(callback.from_user.id, m.media_id)
            elif m.media_type == "video": await bot.send_video(callback.from_user.id, m.media_id)
        except Exception: pass

@dp.callback_query(lambda c: c.data.startswith("hw:edit_text:"))
async def cb_hw_edit_text(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    await state.update_data(hw_id=hw_id)
    await callback.message.edit_text("Напиши новый текст для этого ДЗ:"); await state.set_state(EditHW.text)

@dp.message(EditHW.text)
async def save_hw_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        hw = await session.get(Homework, data["hw_id"])
        if hw: hw.text = message.text; await session.commit()
    await message.answer("✅ Текст обновлен!", reply_markup=hw_menu_teacher()); await state.clear()

@dp.callback_query(lambda c: c.data.startswith("hw:del_ask:"))
async def cb_hw_del_ask(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    b = [[InlineKeyboardButton(text="Да, удалить", callback_data=f"hw:del:{hw_id}")], [InlineKeyboardButton(text="Отмена", callback_data="menu:hw")]]
    await callback.message.edit_text("Точно удалить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:del:"))
async def cb_hw_del(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        for d in (await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id))).scalars().all(): await session.delete(d)
        for m in (await session.execute(select(HomeworkMedia).where(HomeworkMedia.homework_id == hw_id))).scalars().all(): await session.delete(m)
        hw = await session.get(Homework, hw_id)
        if hw: await session.delete(hw)
        await session.commit()
    await callback.message.edit_text("✅ Удалено.", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:list")
async def cb_hw_list(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        hws = (await session.execute(select(Homework).order_by(Homework.id.desc()))).scalars().all()
    if not hws: return await callback.message.edit_text("Пока нет ДЗ.", reply_markup=back_to_main())
    b = []
    for hw in hws:
        is_for_me = (hw.target_student_id is None) or (hw.target_student_id == st.id)
        mark = "🟢 [Для тебя] " if is_for_me else "⚪ [Общее] "
        b.append([InlineKeyboardButton(text=f"{mark}{hw.title}", callback_data=f"hw:view:{hw.id}")])
    b.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    await callback.message.edit_text("📚 Выбери тему:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:view:"))
async def cb_hw_view(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        hw = await session.get(Homework, hw_id)
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        done = (await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id, HomeworkDone.student_id == st.id))).scalar_one_or_none() if st else None
        media = (await session.execute(select(HomeworkMedia).where(HomeworkMedia.homework_id == hw_id))).scalars().all()
    if not hw: return
    text = f"📚 <b>{hw.title}</b>\n\n{hw.text}"
    if hw.deadline: text += f"\n\n📅 Дедлайн: {hw.deadline.strftime('%d.%m.%Y')}"
    kb = hw_submission_keyboard(hw.id) if not done else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="hw:list")]])
    if done: text += "\n\n✅ Вы уже выполнили это задание."
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    for m in media:
        try:
            if m.media_type == "photo": await bot.send_photo(callback.from_user.id, m.media_id)
            elif m.media_type == "video": await bot.send_video(callback.from_user.id, m.media_id)
        except Exception: pass

@dp.callback_query(lambda c: c.data.startswith("hw:attach:"))
async def cb_hw_attach(callback: CallbackQuery, state: FSMContext):
    await callback.answer(); await state.update_data(hw_id=int(callback.data.split(":")[2])); await callback.message.edit_text("Отправь фото/видео:"); await state.set_state(SubmitHW.media)

@dp.message(SubmitHW.media)
async def process_hw_media(message: types.Message, state: FSMContext):
    if not message.photo and not message.video: return await message.answer("Нужно фото/видео.")
    m_t, m_i = ("photo", message.photo[-1].file_id) if message.photo else ("video", message.video.file_id)
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == message.from_user.id))).scalar_one_or_none()
        if st:
            if m_t == "photo": await bot.send_photo(TEACHER_ID, photo=m_i, caption=f"📚 {st.custom_name or st.full_name} прислал фото")
            else: await bot.send_video(TEACHER_ID, video=m_i, caption=f"📚 {st.custom_name or st.full_name} прислал видео")
    await message.answer("✅ Прикреплено.", reply_markup=back_to_main()); await state.clear()

@dp.callback_query(lambda c: c.data.startswith("hw:finish:"))
async def cb_hw_finish(callback: CallbackQuery):
    await callback.answer()
    hw_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        hw = await session.get(Homework, hw_id)
        if st and hw and not (await session.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hw_id, HomeworkDone.student_id == st.id))).scalar_one_or_none():
            session.add(HomeworkDone(homework_id=hw_id, student_id=st.id)); await session.commit()
            await bot.send_message(TEACHER_ID, f"📚 {st.custom_name or st.full_name} сдал ДЗ: {hw.title}")
    await callback.message.edit_text("✅ Передано.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "hw_rem_settings")
async def cb_hw_rem_settings(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
    if st:
        days = st.hw_reminder_days or 1
        txt = text_hw_reminder_settings(days, st.hw_reminder_enabled)
        kb = hw_reminder_keyboard(st.hw_reminder_enabled)
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "hwrem:toggle")
async def cb_hwrem_toggle(callback: CallbackQuery):
    await callback.answer()
    async with async_session() as session:
        st = (await session.execute(select(Student).where(Student.tg_id == callback.from_user.id))).scalar_one_or_none()
        if st: 
            st.hw_reminder_enabled = not st.hw_reminder_enabled
            await session.commit()
    await cb_hw_rem_settings(callback)

@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await callback.answer()
    await callback.message.edit_text("Меню:", reply_markup=main_menu_teacher() if is_teacher(callback.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    await callback.answer(); await callback.message.edit_text(text_help(), reply_markup=back_to_main())

async def health(request): return web.Response(text="OK")
async def on_startup(bot: Bot) -> None:
    await init_db()
    await bot.set_webhook(f"{URL}{PATH}", secret_token=SECRET, drop_pending_updates=True, allowed_updates=["message", "callback_query"])
    start_scheduler(bot)

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=SECRET).register(app, path=PATH)
app.router.add_get("/health", health)
setup_application(app, dp, bot=bot)
dp.startup.register(on_startup)

if __name__ == "__main__":
    web.run_app(app, host=HOST, port=PORT)
