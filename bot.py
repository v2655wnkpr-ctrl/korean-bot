import logging, os
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
logging.basicConfig(level=logging.INFO)
BASE_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://localhost").rstrip("/")
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret-token"
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 8080))
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddLesson(StatesGroup): student, dt, title = State(), State(), State()
class SetTimezone(StatesGroup): choosing_tz = State()
class PayFlow(StatesGroup): choosing_student = State()
class FindStudent(StatesGroup): query = State()
class RescheduleFlow(StatesGroup): dt = State()
class AddHomework(StatesGroup): title, text, media, deadline = State(), State(), State(), State()
class SubmitHW(StatesGroup): media = State()
class PaymentProof(StatesGroup): waiting_photo = State()

def is_teacher(uid): return uid == TEACHER_ID

@dp.message(Command("start"))
async def cmd_start(m: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == m.from_user.id))).scalar_one_or_none()
        if not st:
            s.add(Student(tg_id=m.from_user.id, full_name=m.from_user.full_name, username=m.from_user.username)); await s.commit()
            if m.from_user.id != TEACHER_ID:
                try: await bot.send_message(TEACHER_ID, f"🆕 {m.from_user.full_name} @{m.from_user.username}")
                except: pass
            await m.answer("Выбери пояс:", reply_markup=timezone_offset_keyboard()); return await state.set_state(SetTimezone.choosing_tz)
    await m.answer("Меню:", reply_markup=main_menu_teacher() if is_teacher(m.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data.startswith("tz:"), SetTimezone.choosing_tz)
async def cb_set_tz(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if c.data.split(":")[1] == "other": return await c.message.edit_text("Напиши смещение от МСК:")
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if st: st.timezone_offset = int(c.data.split(":")[1]); await s.commit()
    await c.message.edit_text("✅ Пояс установлен!"); await c.message.answer(text_welcome(), reply_markup=main_menu_student()); await state.clear()

@dp.message(SetTimezone.choosing_tz)
async def set_tz_text(m: types.Message, state: FSMContext):
    try: offset = int(m.text.strip())
    except: return await m.answer("Напиши число:")
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == m.from_user.id))).scalar_one_or_none()
        if st: st.timezone_offset = offset; await s.commit()
    await m.answer("✅ Пояс установлен!", reply_markup=main_menu_student()); await state.clear()

@dp.message(Command("menu"))
async def cmd_menu(m: types.Message): await m.answer("Меню:", reply_markup=main_menu_teacher() if is_teacher(m.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:calendar")
async def cb_calendar(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    now = now_msk()
    async with async_session() as s:
        ls = (await s.execute(select(Lesson).where(Lesson.datetime_start >= datetime(now.year, now.month, 1)))).scalars().all()
        sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await c.message.edit_text("📅 Календарь:", reply_markup=calendar_keyboard(now.year, now.month, {l.datetime_start.day for l in ls if l.datetime_start.month == now.month}, {s.datetime_start.day for s in sl if s.datetime_start.month == now.month}))

@dp.callback_query(lambda c: c.data.startswith("cal:init:"))
async def cb_calendar_init(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    y, m = int(c.data.split(":")[2]), int(c.data.split(":")[3])
    async with async_session() as s:
        ls = (await s.execute(select(Lesson).where(Lesson.datetime_start >= datetime(y, m, 1)))).scalars().all()
        sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await c.message.edit_text("📅 Календарь:", reply_markup=calendar_keyboard(y, m, {l.datetime_start.day for l in ls if l.datetime_start.month == m}, {s.datetime_start.day for s in sl if s.datetime_start.month == m}))

@dp.callback_query(lambda c: c.data == "cal:ignore")
async def cb_cal_ignore(c: CallbackQuery): await c.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:day:"))
async def cb_cal_day(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    y, m, d = map(int, c.data.split(":")[2].split("-"))
    ds, de = datetime(y, m, d, 0, 0), datetime(y, m, d, 23, 59)
    async with async_session() as s:
        ls = (await s.execute(select(Lesson).where(Lesson.datetime_start >= ds, Lesson.datetime_start <= de).order_by(Lesson.datetime_start))).scalars().all()
        sl = (await s.execute(select(LessonSlot).where(LessonSlot.datetime_start >= ds, LessonSlot.datetime_start <= de, LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    lines = [f"📅 {d}.{m:02d}.{y}\n"]
    if ls:
        lines.append("Занятия:")
        for l in ls: lines.append(f"• {l.datetime_start.strftime('%H:%M')} — {l.title}")
        lines.append("")
    if sl:
        lines.append("Слоты:")
        for s in sl: lines.append(f"🟢 {s.datetime_start.strftime('%H:%M')}")
    if not lines[1:]: lines.append("Пусто.")
    await c.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:calendar"))

@dp.callback_query(lambda c: c.data == "menu:slots")
async def cb_slots_menu(c: CallbackQuery):
    await c.answer()
    if is_teacher(c.from_user.id): await c.message.edit_text("📅 Слоты:", reply_markup=slots_menu_teacher())

@dp.callback_query(lambda c: c.data == "slot:show_calendar")
async def cb_slot_show_calendar(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    now = now_msk()
    async with async_session() as s: sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await c.message.edit_text("📅 День:", reply_markup=calendar_keyboard(now.year, now.month, set(), {s.datetime_start.day for s in sl if s.datetime_start.month == now.month}, prefix="slot"))

@dp.callback_query(lambda c: c.data.startswith("slot:day:"))
async def cb_slot_day(c: CallbackQuery, state: FSMContext):
    await c.answer()
    y, m, d = map(int, c.data.split(":")[2].split("-"))
    await state.update_data(date_str=datetime(y, m, d).strftime("%Y-%m-%d"), selected_times=[])
    await c.message.edit_text(f"📅 {d}.{m:02d}.{y}\n\nВремя:", reply_markup=time_picker_keyboard())

@dp.callback_query(lambda c: c.data.startswith("slot:init:"))
async def cb_slot_init(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    y, m = int(c.data.split(":")[2]), int(c.data.split(":")[3])
    async with async_session() as s: sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False))).scalars().all()
    await c.message.edit_text("📅 День:", reply_markup=calendar_keyboard(y, m, set(), {s.datetime_start.day for s in sl if s.datetime_start.month == m}, prefix="slot"))

@dp.callback_query(lambda c: c.data.startswith("time:"))
async def cb_time_pick(c: CallbackQuery, state: FSMContext):
    ts = c.data.split(":", 1)[1]
    data = await state.get_data()
    if not data.get("date_str"): return await c.answer("Ошибка.", show_alert=True)
    if ts == "save":
        sel = data.get("selected_times", [])
        if not sel: return await c.answer("Не выбрано!", show_alert=True)
        async with async_session() as s:
            for t in sel: s.add(LessonSlot(teacher_id=TEACHER_ID, datetime_start=datetime.strptime(f"{data['date_str']} {t}", "%Y-%m-%d %H:%M")))
            await s.commit()
        await c.message.edit_text(f"✅ Открыто: {len(sel)}", reply_markup=slots_menu_teacher()); await state.clear(); return await c.answer()
    sel = data.get("selected_times", [])
    if ts in sel: sel.remove(ts)
    else: sel.append(ts)
    await state.update_data(selected_times=sel); await c.message.edit_reply_markup(reply_markup=time_picker_keyboard(set(sel))); await c.answer()

@dp.callback_query(lambda c: c.data == "slot:list")
async def cb_slot_list(c: CallbackQuery):
    await c.answer()
    async with async_session() as s: sl = (await s.execute(select(LessonSlot).where(LessonSlot.teacher_id == TEACHER_ID, LessonSlot.is_booked == False, LessonSlot.datetime_start >= now_msk()).order_by(LessonSlot.datetime_start))).scalars().all()
    if not sl: return await c.message.edit_text("Нет слотов.", reply_markup=slots_menu_teacher())
    await c.message.edit_text("📅 <b>Слоты:</b>\nНажми ❌:", reply_markup=slots_delete_keyboard(sl))

@dp.callback_query(lambda c: c.data.startswith("slot:del:"))
async def cb_slot_del(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s:
        sl = await s.get(LessonSlot, int(c.data.split(":")[2]))
        if sl and not sl.is_booked: await s.delete(sl); await s.commit(); await c.message.answer("✅ Закрыт.")
    await cb_slot_list(c)

@dp.callback_query(lambda c: c.data == "menu:stats")
async def cb_stats(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s:
        stc = len((await s.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all())
        lsc = len((await s.execute(select(Lesson))).scalars().all())
        ftc = len((await s.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()))).scalars().all())
        slc = len((await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False, LessonSlot.datetime_start >= now_msk()))).scalars().all())
    await c.message.edit_text(f"📊 <b>Стата</b>\n👥 {stc}\n📚 {lsc}\n📅 {ftc}\n🟢 {slc}", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: sts = (await s.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not sts: return await c.message.edit_text("Нет учеников.", reply_markup=back_to_main())
    lines, data = ["👥 Кому:\n"], {"total": len(sts)}
    for i, st in enumerate(sts, 1): lines.append(f"{i}. {st.full_name}"); data[f"s_{i}"] = st.id
    await c.message.edit_text("\n".join(lines) + f"\nНомер 1–{len(sts)}", reply_markup=back_to_main())
    await state.update_data(**data); await state.set_state(AddLesson.student)

@dp.message(AddLesson.student)
async def add_student(m: types.Message, state: FSMContext):
    data, txt = await state.get_data(), m.text.strip()
    sid = data.get(f"s_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if not sid:
        low = txt.lower().lstrip("@")
        async with async_session() as s:
            for st in (await s.execute(select(Student))).scalars().all():
                if st.tg_id != TEACHER_ID and (low == (st.username or "").lower() or low in st.full_name.lower()): sid = st.id; break
    if not sid: return await m.answer("Нет.")
    async with async_session() as s:
        st = await s.get(Student, sid)
        sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    await state.update_data(sid=st.id, sname=st.full_name)
    if sl: await m.answer("Слот или дата:", reply_markup=slots_picker_keyboard(sl, sid))
    else: await m.answer("Дата (ДД.ММ.ГГГГ ЧЧ:ММ):"); await state.set_state(AddLesson.dt)

@dp.callback_query(lambda c: c.data.startswith("act_slot:"))
async def cb_act_slot(c: CallbackQuery, state: FSMContext):
    await c.answer()
    _, sid, slid = c.data.split(":")
    async with async_session() as s:
        sl, st = await s.get(LessonSlot, int(slid)), await s.get(Student, int(sid))
        if sl and st:
            sl.is_booked = True; await s.commit()
            await state.update_data(sid=st.id, sname=st.full_name, dt=sl.datetime_start)
            await c.message.edit_text("Название:"); await state.set_state(AddLesson.title)

@dp.callback_query(lambda c: c.data.startswith("act_manual:"))
async def cb_act_manual(c: CallbackQuery, state: FSMContext):
    await c.answer()
    async with async_session() as s: st = await s.get(Student, int(c.data.split(":")[1]))
    if st: await state.update_data(sid=st.id, sname=st.full_name); await c.message.edit_text("Дата:"); await state.set_state(AddLesson.dt)

@dp.message(AddLesson.dt)
async def add_dt(m: types.Message, state: FSMContext):
    try: dt = datetime.strptime(m.text.strip(), "%d.%m.%Y %H:%M")
    except: return await m.answer("Формат: 15.10.2026 18:30")
    await state.update_data(dt=dt); await m.answer("Название:"); await state.set_state(AddLesson.title)

@dp.message(AddLesson.title)
async def add_title(m: types.Message, state: FSMContext):
    data = await state.get_data()
    title = m.text.strip() if m.text.strip() != "-" else "Корейский"
    async with async_session() as s: s.add(Lesson(student_id=data["sid"], datetime_start=data["dt"], title=title)); await s.commit()
    await m.answer(f"✅ {data['sname']}\n{data['dt'].strftime('%d.%m %H:%M')}", reply_markup=main_menu_teacher()); await state.clear()
@dp.callback_query(lambda c: c.data == "menu:hw")
async def cb_hw_menu(c: CallbackQuery):
    await c.answer()
    if is_teacher(c.from_user.id): await c.message.edit_text("📚 ДЗ", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:create")
async def cb_hw_create(c: CallbackQuery, state: FSMContext):
    await c.answer(); await c.message.edit_text("Тема ДЗ:"); await state.set_state(AddHomework.title)

@dp.message(AddHomework.title)
async def hw_title(m: types.Message, state: FSMContext):
    await state.update_data(title=m.text); await m.answer("Текст:"); await state.set_state(AddHomework.text)

@dp.message(AddHomework.text)
async def hw_text(m: types.Message, state: FSMContext):
    await state.update_data(text=m.text); await m.answer("Материал или «-»:"); await state.set_state(AddHomework.media)

@dp.message(AddHomework.media)
async def hw_media(m: types.Message, state: FSMContext):
    mt, mi, ci = ("video", str(m.message_id), m.chat.id) if m.video else ("photo", str(m.message_id), m.chat.id) if m.photo else (None, None, None) if m.text == "-" else (None, None, None)
    if not mt and m.text != "-": return await m.answer("Видео или «-»:")
    await state.update_data(mt=mt, mi=mi, ci=ci); await m.answer(text_hw_add_deadline()); await state.set_state(AddHomework.deadline)

@dp.message(AddHomework.deadline)
async def hw_deadline(m: types.Message, state: FSMContext):
    data, txt = await state.get_data(), m.text.strip()
    dl = None
    if txt != "-":
        try: dl = datetime.strptime(txt, "%d.%m.%Y")
        except: return await m.answer("Формат: 25.10.2026")
    async with async_session() as s: s.add(Homework(title=data["title"], text=data["text"], media_type=data.get("mt"), media_id=data.get("mi"), chat_id=data.get("ci"), deadline=dl)); await s.commit()
    await m.answer("✅ ДЗ создано!", reply_markup=main_menu_teacher()); await state.clear()

@dp.callback_query(lambda c: c.data == "hw:list_teacher")
async def cb_hw_list_teacher(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: hws = (await s.execute(select(Homework).order_by(Homework.id.desc()))).scalars().all()
    if not hws: return await c.message.edit_text("Нет ДЗ.", reply_markup=hw_menu_teacher())
    b = [[InlineKeyboardButton(text=f"{hw.created_at.strftime('%d.%m')} — {hw.title}", callback_data=f"hw:view_teacher:{hw.id}")] for hw in hws]
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:hw")])
    await c.message.edit_text("📚 Выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:view_teacher:"))
async def cb_hw_view_teacher(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: hw = await s.get(Homework, int(c.data.split(":")[2]))
    if not hw: return
    text = f"📚 {hw.title}\n\n{hw.text}"
    if hw.deadline: text += f"\n📅 {hw.deadline.strftime('%d.%m.%Y')}"
    b = [[InlineKeyboardButton(text="Удалить", callback_data=f"hw:del_ask:{hw.id}")], [InlineKeyboardButton(text="Назад", callback_data="hw:list_teacher")]]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:del_ask:"))
async def cb_hw_del_ask(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    b = [[InlineKeyboardButton(text="Да", callback_data=f"hw:del:{c.data.split(':')[2]}")], [InlineKeyboardButton(text="Нет", callback_data=f"hw:view_teacher:{c.data.split(':')[2]}")]]
    await c.message.edit_text("Удалить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:del:"))
async def cb_hw_del(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    hid = int(c.data.split(":")[1])
    async with async_session() as s:
        hw = await s.get(Homework, hid)
        if hw:
            for d in (await s.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hid))).scalars().all(): await s.delete(d)
            for sub in (await s.execute(select(HomeworkSubmission).where(HomeworkSubmission.homework_id == hid))).scalars().all(): await s.delete(sub)
            await s.delete(hw); await s.commit()
    await c.message.edit_text("✅ Удалено.", reply_markup=hw_menu_teacher())

@dp.callback_query(lambda c: c.data == "hw:list")
async def cb_hw_list(c: CallbackQuery):
    await c.answer()
    async with async_session() as s: hws = (await s.execute(select(Homework).order_by(Homework.id.desc()))).scalars().all()
    if not hws: return await c.message.edit_text("Нет ДЗ.", reply_markup=back_to_main())
    b = [[InlineKeyboardButton(text=hw.title, callback_data=f"hw:view:{hw.id}")] for hw in hws]
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:main")])
    await c.message.edit_text("📚 Тема:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("hw:view:"))
async def cb_hw_view(c: CallbackQuery):
    await c.answer()
    hid = int(c.data.split(":")[2])
    async with async_session() as s:
        hw = await s.get(Homework, hid)
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        done = (await s.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hid, HomeworkDone.student_id == st.id))).scalar_one_or_none() if st else None
    if not hw: return
    text = f"📚 {hw.title}\n\n{hw.text}"
    if hw.deadline: text += f"\n📅 {hw.deadline.strftime('%d.%m.%Y')}"
    kb = hw_submission_keyboard(hw.id) if not done else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="hw:list")]])
    if done: text += "\n\n✅ Выполнено."
    try:
        if hw.media_type in ("photo", "video") and hw.chat_id: await bot.copy_message(c.from_user.id, hw.chat_id, int(hw.media_id), caption=text, reply_markup=kb)
        else: await c.message.edit_text(text, reply_markup=kb)
    except: await c.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("hw:attach:"))
async def cb_hw_attach(c: CallbackQuery, state: FSMContext):
    await c.answer(); await state.update_data(hid=int(c.data.split(":")[2])); await c.message.edit_text("Файл:"); await state.set_state(SubmitHW.media)

@dp.message(SubmitHW.media)
async def process_hw_media(m: types.Message, state: FSMContext):
    if not m.photo and not m.video: return await m.answer("Фото/видео.")
    mt, mi = ("photo", m.photo[-1].file_id) if m.photo else ("video", m.video.file_id)
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == m.from_user.id))).scalar_one_or_none()
        if st:
            s.add(HomeworkSubmission(homework_id=(await state.get_data()).get("hid"), student_id=st.id, media_type=mt, media_id=mi)); await s.commit()
            if mt == "photo": await bot.send_photo(TEACHER_ID, photo=mi, caption=f"📚 {st.full_name}")
            else: await bot.send_video(TEACHER_ID, video=mi, caption=f"📚 {st.full_name}")
    await m.answer("✅ Прикреплено."); await state.clear()

@dp.callback_query(lambda c: c.data.startswith("hw:finish:"))
async def cb_hw_finish(c: CallbackQuery):
    await c.answer()
    hid = int(c.data.split(":")[2])
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        hw = await s.get(Homework, hid)
        if st and hw and not (await s.execute(select(HomeworkDone).where(HomeworkDone.homework_id == hid, HomeworkDone.student_id == st.id))).scalar_one_or_none():
            s.add(HomeworkDone(homework_id=hid, student_id=st.id)); await s.commit()
            await bot.send_message(TEACHER_ID, f"📚 {st.full_name} сдал")
    await c.message.edit_text("✅ Передано.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "hw_rem_settings")
async def cb_hw_rem_settings(c: CallbackQuery):
    await c.answer()
    async with async_session() as s: st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
    if st: await c.message.edit_text(f"⚙️ <b>ДЗ</b>\n{'✅ Вкл' if st.hw_reminder_enabled else '❌ Выкл'}", reply_markup=hw_reminder_keyboard(st.hw_reminder_enabled), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "hwrem:toggle")
async def cb_hwrem_toggle(c: CallbackQuery):
    await c.answer()
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if st: st.hw_reminder_enabled = not st.hw_reminder_enabled; await s.commit()
    await cb_hw_rem_settings(c)

@dp.callback_query(lambda c: c.data == "menu:lessons")
async def cb_student_lessons(c: CallbackQuery):
    await c.answer()
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if not st: return
        up = (await s.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
        past = (await s.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start < now_msk()).order_by(Lesson.datetime_start.desc()).limit(5))).scalars().all()
    lines = ["📅 <b>Занятия:</b>\n"]
    if up:
        lines.append("<b>Предстоящие:</b>")
        for l in up: lines.append(f"• {(l.datetime_start + timedelta(hours=st.timezone_offset)).strftime('%d.%m %H:%M')} — {l.title}")
        lines.append("")
    else: lines.append("Нет.\n")
    if past:
        lines.append("<b>Прошедшие:</b>")
        for l in past: lines.append(f"✓ {(l.datetime_start + timedelta(hours=st.timezone_offset)).strftime('%d.%m %H:%M')} — {l.title}")
    kb = [[InlineKeyboardButton(text="Перенести", callback_data="transfer:click", icon_custom_emoji_id=E_RESCHED)]] if up else []
    kb.append([InlineKeyboardButton(text="Назад", callback_data="menu:main", icon_custom_emoji_id=E_BACK)])
    await c.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "menu:settings")
async def cb_settings_menu(c: CallbackQuery):
    await c.answer()
    async with async_session() as s: st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
    if st: await c.message.edit_text(f"⚙️ <b>Напоминания</b>\nСейчас: <b>{st.lesson_reminder_hours or 2} ч.</b>", reply_markup=student_lesson_reminders_keyboard(st.lesson_reminder_hours or 2), parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("lrem:"))
async def cb_lrem_hours(c: CallbackQuery):
    await c.answer()
    hours = int(c.data.split(":")[1])
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if st: st.lesson_reminder_hours = hours; await s.commit()
    await c.answer(f"За {hours} ч.", show_alert=True)
    await cb_settings_menu(c)

@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(c: CallbackQuery, state: FSMContext):
    await c.answer(); await c.message.edit_text("Как?", reply_markup=student_transfer_menu())

@dp.callback_query(lambda c: c.data == "transfer:ask_teacher")
async def cb_transfer_ask_teacher(c: CallbackQuery):
    await c.answer(); await c.message.edit_text(f"👉 {TEACHER_LINK}", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "transfer:ask_slot")
async def cb_transfer_ask_slot(c: CallbackQuery):
    await c.answer()
    async with async_session() as s: sl = (await s.execute(select(LessonSlot).where(LessonSlot.is_booked == False).order_by(LessonSlot.datetime_start))).scalars().all()
    if not sl: return await c.message.edit_text("Нет слотов.", reply_markup=back_to_main())
    b = [[InlineKeyboardButton(text=s.datetime_start.strftime("%d.%m %H:%M"), callback_data=f"transfer:pick:{s.id}")] for s in sl[:10]]
    b.append([InlineKeyboardButton(text="Назад", callback_data="menu:main")])
    await c.message.edit_text("Время:", reply_markup=InlineKeyboardMarkup(inline_keyboard=b))

@dp.callback_query(lambda c: c.data.startswith("transfer:pick:"))
async def cb_transfer_pick(c: CallbackQuery):
    await c.answer()
    async with async_session() as s:
        sl = await s.get(LessonSlot, int(c.data.split(":")[2]))
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if not st or not sl: return
        lesson = (await s.execute(select(Lesson).where(Lesson.student_id == st.id, Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().first()
        if not lesson: return await c.message.edit_text("Нет занятий.", reply_markup=back_to_main())
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да", callback_data=f"transfer:approve:{lesson.id}:{sl.id}"), InlineKeyboardButton(text="❌ Нет", callback_data=f"transfer:decline:{sl.id}:{st.tg_id}")]])
        await bot.send_message(TEACHER_ID, f"🔄 {st.full_name}\n{lesson.datetime_start.strftime('%d.%m %H:%M')}\nХочет: {sl.datetime_start.strftime('%d.%m %H:%M')}", reply_markup=kb)
        sl.is_booked = True; await s.commit()
    await c.message.edit_text("✅ Отправлено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data.startswith("transfer:approve:"))
async def cb_transfer_approve(c: CallbackQuery):
    await c.answer("OK")
    if not is_teacher(c.from_user.id): return
    _, _, lid, sid = c.data.split(":")
    async with async_session() as s:
        lesson, sl = await s.get(Lesson, int(lid)), await s.get(LessonSlot, int(sid))
        if lesson and sl:
            lesson.datetime_start = sl.datetime_start; await s.delete(sl); await s.commit()
            await c.message.edit_text("✅ Перенесено.")
            st = (await s.execute(select(Student).where(Student.id == lesson.student_id))).scalar_one_or_none()
            if st: await bot.send_message(st.tg_id, f"✅ Новое время: {lesson.datetime_start.strftime('%d.%m %H:%M')}")

@dp.callback_query(lambda c: c.data.startswith("transfer:decline:"))
async def cb_transfer_decline(c: CallbackQuery):
    await c.answer("Нет")
    if not is_teacher(c.from_user.id): return
    p = c.data.split(":")
    async with async_session() as s:
        sl = await s.get(LessonSlot, int(p[2]))
        if sl: sl.is_booked = False; await s.commit()
    await c.message.edit_text("❌ Отклонено.")
    if len(p) > 3:
        try: await bot.send_message(int(p[3]), "❌ Преподаватель не может согласовать это время. Скоро свяжусь с вами.")
        except: pass

@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(c: CallbackQuery):
    await c.answer()
    if is_teacher(c.from_user.id): await c.message.edit_text("💰 Оплата", reply_markup=pay_menu())

@dp.callback_query(lambda c: c.data.startswith("pay:"))
async def cb_pay_choose(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if c.data in ["pay:show_tariffs", "pay:single:req", "pay:back"]: return
    if not is_teacher(c.from_user.id): return
    mode = c.data.split(":")[1]
    async with async_session() as s: sts = (await s.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not sts: return await c.message.edit_text("Нет учеников.", reply_markup=back_to_main("menu:pay"))
    lines, data = ["👥 Кому:\n"], {"mode": mode, "total": len(sts)}
    for i, st in enumerate(sts, 1): lines.append(f"{i}. {st.full_name}"); data[f"st_{i}"] = st.tg_id
    await state.update_data(**data); await state.set_state(PayFlow.choosing_student)
    await c.message.edit_text("\n".join(lines) + f"\nНомер 1–{len(sts)}:", reply_markup=back_to_main("menu:pay"))

@dp.message(PayFlow.choosing_student)
async def pay_send(m: types.Message, state: FSMContext):
    if not is_teacher(m.from_user.id): return
    data, txt = await state.get_data(), m.text.strip()
    tg = data.get(f"st_{int(txt)}") if txt.isdigit() and 1 <= int(txt) <= data.get("total", 0) else None
    if not tg:
        low = txt.lower().lstrip("@")
        async with async_session() as s:
            for st in (await s.execute(select(Student))).scalars().all():
                if st.tg_id != TEACHER_ID and (low == (st.username or "").lower() or low in st.full_name.lower()): tg = st.tg_id; break
    if not tg: return await m.answer("Нет.")
    if data.get("mode") == "after":
        text, kb = text_pay_after_button(), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить", callback_data="pay:single:req")], [InlineKeyboardButton(text="📚 Тарифы", callback_data="pay:show_tariffs:single")]])
    else:
        text, kb = text_pay_end_button(), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Абонемент", callback_data="pay:show_tariffs:sub")]])
    try: await bot.send_message(tg, text, reply_markup=kb, parse_mode="HTML")
    except: pass
    await state.clear(); await m.answer("✅ Отправлено.", reply_markup=back_to_main("menu:pay"))

@dp.callback_query(lambda c: c.data.startswith("pay:show_tariffs"))
async def cb_pay_show_tariffs(c: CallbackQuery):
    await c.answer()
    ctx = c.data.split(":")[2] if len(c.data.split(":")) > 2 else "single"
    text = "📚 <b>Тарифы:</b>\n\n• Индивид (4) — 4000 ₽\n• Индивид (8) — 7000 ₽\n• Группа (4) — 2000 ₽\n• Группа (8) — 3500 ₽"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Индивид 4", callback_data=f"tar:ind_4:{ctx}")], [InlineKeyboardButton(text="Индивид 8", callback_data=f"tar:ind_8:{ctx}")], [InlineKeyboardButton(text="Группа 4", callback_data=f"tar:grp_4:{ctx}")], [InlineKeyboardButton(text="Группа 8", callback_data=f"tar:grp_8:{ctx}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:back:{ctx}", icon_custom_emoji_id=E_BACK)]])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("pay:back:"))
async def cb_pay_back(c: CallbackQuery):
    await c.answer()
    ctx = c.data.split(":")[2]
    if ctx == "single": text, kb = text_pay_after_button(), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить", callback_data="pay:single:req")], [InlineKeyboardButton(text="📚 Тарифы", callback_data="pay:show_tariffs:single")]])
    else: text, kb = text_pay_end_button(), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Абонемент", callback_data="pay:show_tariffs:sub")]])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("tar:"))
async def cb_tariff_chosen(c: CallbackQuery):
    await c.answer()
    p = c.data.split(":")
    ctx = p[2] if len(p) > 2 else "single"
    price = {"ind_4": "4000 ₽", "ind_8": "7000 ₽", "grp_4": "2000 ₽", "grp_8": "3500 ₽"}.get(p[1], "Уточняйте")
    text = f"Вы выбрали: <b>{price}</b>\n\n<b>Реквизиты:</b>\nЯндекс Банк: <code>+7 927 217-38-06</code>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:show_tariffs:{ctx}", icon_custom_emoji_id=E_BACK)]])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "pay:single:req")
async def cb_pay_single_req(c: CallbackQuery):
    await c.answer()
    text = f"<b>Разовое</b>\nСтоимость: <b>1500 ₽</b>\n\n<b>Реквизиты:</b>\nЯндекс Банк: <code>+7 927 217-38-06</code>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📸 Скриншот", callback_data="paid:send_screenshot")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="pay:back:single", icon_custom_emoji_id=E_BACK)]])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "paid:send_screenshot")
async def cb_paid_screenshot(c: CallbackQuery, state: FSMContext):
    await c.answer(); await c.message.edit_text("Отправьте скриншот:"); await state.set_state(PaymentProof.waiting_photo)

@dp.message(PaymentProof.waiting_photo)
async def process_payment_proof(m: types.Message, state: FSMContext):
    if not m.photo: return await m.answer("Фото.")
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == m.from_user.id))).scalar_one_or_none()
        if st:
            await bot.forward_message(chat_id=TEACHER_ID, from_chat_id=m.chat.id, message_id=m.message_id)
            await bot.send_message(TEACHER_ID, f"💰 {st.full_name} скрин!")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data="paid:click")]])
    await m.answer("✅ Скриншот отправлен! Нажмите кнопку ниже.", reply_markup=kb); await state.clear()

@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(c: CallbackQuery):
    await c.answer("ОК", show_alert=True)
    async with async_session() as s:
        st = (await s.execute(select(Student).where(Student.tg_id == c.from_user.id))).scalar_one_or_none()
        if st: await bot.send_message(TEACHER_ID, f"💰 {st.full_name} нажал 'Оплатил'!")
    await c.message.edit_text("✅ Преподаватель уведомлен!", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "sp:open")
async def cb_sp_open(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: sts = (await s.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not sts: return await c.message.edit_text("Нет.", reply_markup=back_to_main())
    await c.message.edit_text("💰 Абонемент:", reply_markup=set_paid_students_keyboard(sts))

@dp.callback_query(lambda c: c.data.startswith("sp:"))
async def cb_set_paid(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    if c.data == "sp:open": return await cb_sp_open(c)
    async with async_session() as s: st = await s.get(Student, int(c.data.split(":")[1]))
    if st: await c.message.edit_text(f"💰 {st.full_name}\nОплачено: {st.paid_lessons or 0}", reply_markup=set_paid_amounts_keyboard(st.id, st.paid_lessons or 0))

@dp.callback_query(lambda c: c.data.startswith("spa:"))
async def cb_set_paid_amount(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    _, sid, amt = c.data.split(":")
    async with async_session() as s:
        st = await s.get(Student, int(sid))
        if st:
            st.paid_lessons = max(0, int(amt)); await s.commit()
            await c.message.edit_text(f"💰 {st.full_name}\nОплачено: {st.paid_lessons}", reply_markup=set_paid_amounts_keyboard(st.id, st.paid_lessons))

@dp.callback_query(lambda c: c.data == "ignore")
async def cb_ignore(c: CallbackQuery): await c.answer()

@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(c: CallbackQuery, state: FSMContext):
    await state.clear(); await c.answer()
    await c.message.edit_text("Меню:", reply_markup=main_menu_teacher() if is_teacher(c.from_user.id) else main_menu_student())

@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(c: CallbackQuery):
    await c.answer(); await c.message.edit_text(text_help(), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s:
        ls = (await s.execute(select(Lesson).order_by(Lesson.datetime_start))).scalars().all()
        sm = {st.id: st.full_name for st in (await s.execute(select(Student))).scalars().all()}
    if not ls: return await c.message.edit_text("Нет.", reply_markup=back_to_main())
    lines = []
    for t, grp in [("📅 Предстоящие:", [l for l in ls if l.datetime_start >= now_msk()]), ("\n✓ Прошедшие:", [l for l in ls if l.datetime_start < now_msk()][-10:])]:
        if grp:
            lines.append(t)
            for l in grp: lines.append(f"• {l.datetime_start.strftime('%d.%m %H:%M')} — {sm.get(l.student_id, '?')}")
    await c.message.edit_text("\n".join(lines), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: ls = (await s.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not ls: return await c.message.edit_text("Нет.", reply_markup=back_to_main())
    await c.message.edit_text("🗑 Удалить:", reply_markup=lessons_action_keyboard(ls, "del"))

@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: l = await s.get(Lesson, int(c.data.split(":")[1]))
    if l: await c.message.edit_text(f"Удалить?", reply_markup=confirm_delete_keyboard(l.id))

@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s:
        l = await s.get(Lesson, int(c.data.split(":")[1]))
        if l: await s.delete(l); await s.commit()
    await c.message.edit_text("✅ Удалено.", reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: sts = (await s.execute(select(Student).where(Student.tg_id != TEACHER_ID))).scalars().all()
    if not sts: return await c.message.edit_text("Нет.", reply_markup=back_to_main())
    await c.message.edit_text("👥:\n" + "\n".join([f"{i}. {st.full_name} @{st.username or '—'}" for i, st in enumerate(sts, 1)]), reply_markup=back_to_main())

@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    await c.message.edit_text("🔍:", reply_markup=back_to_main()); await state.set_state(FindStudent.query)

@dp.message(FindStudent.query)
async def find_query(m: types.Message, state: FSMContext):
    if not is_teacher(m.from_user.id): return
    low = m.text.strip().lower().lstrip("@")
    async with async_session() as s: all_s = (await s.execute(select(Student))).scalars().all()
    f = [st for st in all_s if st.tg_id != TEACHER_ID and (low in st.full_name.lower() or low == (st.username or "").lower())]
    if not f: await m.answer("❌ Нет.", reply_markup=back_to_main()); return await state.clear()
    st = f[0]
    await m.answer(f"👤 {st.full_name}\nID: {st.tg_id}\nОплачено: {st.paid_lessons or 0}", reply_markup=card_keyboard(st.id)); await state.clear()

@dp.callback_query(lambda c: c.data == "menu:reschedule")
async def cb_reschedule(c: CallbackQuery):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    async with async_session() as s: ls = (await s.execute(select(Lesson).where(Lesson.datetime_start >= now_msk()).order_by(Lesson.datetime_start))).scalars().all()
    if not ls: return await c.message.edit_text("Нет.", reply_markup=back_to_main())
    await c.message.edit_text("🔄:", reply_markup=lessons_action_keyboard(ls, "resch"))

@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(c: CallbackQuery, state: FSMContext):
    await c.answer()
    if not is_teacher(c.from_user.id): return
    await state.update_data(lid=int(c.data.split(":")[1])); await c.message.edit_text("Дата:"); await state.set_state(RescheduleFlow.dt)

@dp.message(RescheduleFlow.dt)
async def resch_apply(m: types.Message, state: FSMContext):
    if not is_teacher(m.from_user.id): return
    try: new_dt = datetime.strptime(m.text.strip(), "%d.%m.%Y %H:%M")
    except: return await m.answer("Формат: 15.10.2026 18:30")
    async with async_session() as s:
        l = await s.get(Lesson, (await state.get_data()).get("lid"))
        if l: l.datetime_start = new_dt; await s.commit()
    await m.answer("✅ Перенесено!", reply_markup=main_menu_teacher()); await state.clear()

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
