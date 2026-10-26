import logging
import os
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup,
    CallbackQuery,
)
from dotenv import load_dotenv
from sqlalchemy import select

from database import init_db, async_session
from models import Student, Lesson
from scheduler import start_scheduler, now_msk
from texts import (
    text_help,
    hours_text,
    text_pay_after_button,
    text_pay_end_button,
    text_payment_received,
    text_welcome,
    text_transfer_ask,
    text_transfer_sent,
    text_transfer_cancel,
    text_tariffs,
)
from keyboards import (
    main_menu_student,
    main_menu_teacher,
    back_to_main,
    hours_keyboard,
    pay_menu,
    tariffs_keyboard,
    card_keyboard,
    set_paid_students_keyboard,
    set_paid_amounts_keyboard,
    paid_button_keyboard,
    back_from_paid_keyboard,
    transfer_cancel_keyboard,
    lessons_action_keyboard,
    confirm_delete_keyboard,
    confirm_delete_student_keyboard,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = 932503024

if not BOT_TOKEN:
    msg = "Не найден BOT_TOKEN"
    raise ValueError(msg)

logging.basicConfig(level=logging.INFO)

URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost")
PATH = "/webhook"
SECRET = "my-secret-token"
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class AddLesson(StatesGroup):
    student = State()
    dt = State()
    title = State()


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


def is_teacher(uid: int) -> bool:
    return uid == TEACHER_ID


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    uid = user.id
    is_new = False

    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()

        if student is None:
            is_new = True
            student = Student(
                tg_id=uid,
                full_name=user.full_name,
                username=user.username,
            )
            session.add(student)
            await session.commit()

            if uid != TEACHER_ID:
                un = user.username or "—"
                txt = (
                    "🆕 Новый ученик!\n\n"
                    f"{user.full_name}\n"
                    f"@{un}\n"
                    f"ID: {uid}"
                )
                try:
                    await bot.send_message(TEACHER_ID, txt)
                except Exception as e:
                    logging.error(f"Ош: {e}")

    if is_new and not is_teacher(uid):
        txt = text_welcome()
        kb = main_menu_student()
        await message.answer(txt, reply_markup=kb)
        return

    if is_teacher(uid):
        txt = "👋 Привет, преподаватель!"
        kb = main_menu_teacher()
    else:
        txt = f"👋 Привет, {user.full_name}!"
        kb = main_menu_student()

    await message.answer(txt, reply_markup=kb)


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    uid = message.from_user.id
    if is_teacher(uid):
        kb = main_menu_teacher()
    else:
        kb = main_menu_student()
    await message.answer("Главное меню:", reply_markup=kb)


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    uid = message.from_user.id
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()

    if not student:
        await message.answer("Сначала /start")
        return

    hours = student.custom_hours_before or 2
    txt = f"⚙️ Напоминания\n\nСейчас {hours_text(hours)}."
    await message.answer(txt, reply_markup=hours_keyboard())


@dp.message(Command("set_paid"))
async def cmd_set_paid(message: types.Message):
    uid = message.from_user.id
    if not is_teacher(uid):
        await message.answer("Только для препода.")
        return

    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id != TEACHER_ID)
        r = await session.execute(q)
        students = r.scalars().all()

    if not students:
        await message.answer("Нет учеников.")
        return

    txt = "💰 Отметить оплату\n\nВыбери ученика:"
    kb = set_paid_students_keyboard(students)
    await message.answer(txt, reply_markup=kb)


@dp.message(Command("pay"))
async def cmd_pay(message: types.Message):
    uid = message.from_user.id
    if not is_teacher(uid):
        await message.answer("Только для препода.")
        return
    txt = "💰 Оплата и напоминания\n\nЧто отправить?"
    await message.answer(txt, reply_markup=pay_menu())


@dp.callback_query(lambda c: c.data == "sp:open")
async def cb_sp_open(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return

    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id != TEACHER_ID)
        r = await session.execute(q)
        students = r.scalars().all()

    if not students:
        await callback.answer("Нет учеников")
        return

    txt = "💰 Отметить оплату\n\nВыбери ученика:"
    kb = set_paid_students_keyboard(students)
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("sp:"))
async def cb_set_paid(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    if callback.data == "sp:open":
        await cb_sp_open(callback)
        return
    
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = await session.get(Student, sid)
        
    if not student:
        await callback.answer("Не найден")
        return
    
    paid = student.paid_lessons or 0
    txt = (
        f"💰 {student.full_name}\n\n"
        f"Сейчас оплачено: {paid}"
    )
    kb = set_paid_amounts_keyboard(sid, paid)
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("spa:"))
async def cb_set_paid_amount(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    
    parts = callback.data.split(":")
    sid = int(parts[1])
    amount = int(parts[2])
    
    if amount < 0:
        amount = 0
        
    async with async_session() as session:
        student = await session.get(Student, sid)
        if not student:
            await callback.answer("Не найден")
            return
        student.paid_lessons = amount
        student.last_payment_reminder = None
        await session.commit()
        
    paid = student.paid_lessons or 0
    txt = (
        f"💰 {student.full_name}\n\n"
        f"Сейчас оплачено: {paid}"
    )
    kb = set_paid_amounts_keyboard(sid, paid)
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer(f"Оплачено: {amount}")


@dp.callback_query(lambda c: c.data == "ignore")
async def cb_ignore(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(callback: CallbackQuery):
    uid = callback.from_user.id
    if is_teacher(uid):
        kb = main_menu_teacher()
    else:
        kb = main_menu_student()
    await callback.message.edit_text("Меню:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    kb = back_to_main()
    await callback.message.edit_text(text_help(), reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:settings")
async def cb_settings(callback: CallbackQuery):
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
        
    if not student:
        await callback.answer("Сначала /start")
        return
        
    hours = student.custom_hours_before or 2
    txt = f"⚙️ Напоминания\n\nСейчас {hours_text(hours)}."
    kb = hours_keyboard()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("h:"))
async def cb_hours(callback: CallbackQuery):
    hours = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
        if student:
            student.custom_hours_before = hours
            await session.commit()
            
    txt = f"✅ Готово!\n\nНапомню {hours_text(hours)}."
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:lessons")
async def cb_lessons(callback: CallbackQuery):
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
        
        if not student:
            await callback.answer("Сначала /start")
            return
            
        q2 = select(Lesson)
        q2 = q2.where(Lesson.student_id == student.id)
        q2 = q2.order_by(Lesson.datetime_start)
        r2 = await session.execute(q2)
        lessons = r2.scalars().all()
        
    if not lessons:
        kb = back_to_main()
        await callback.message.edit_text("📅 Пока нет занятий.", reply_markup=kb)
        await callback.answer()
        return
        
    now = now_msk()
    lines = ["📅 Твои занятия:\n"]
    for les in lessons:
        dt = les.datetime_start
        mark = "✓" if dt < now else "•"
        s = dt.strftime("%d.%m %H:%M")
        lines.append(f"{mark} {s} — {les.title}")
        
    txt = "\n".join(lines)
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id != TEACHER_ID)
        result = await session.execute(q)
        students = result.scalars().all()
        
    if not students:
        kb = back_to_main()
        await callback.message.edit_text("Нет учеников.", reply_markup=kb)
        await callback.answer()
        return
        
    lines = ["👥 Выбери ученика:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
        
    lines.append(f"\nНапиши номер 1–{len(students)}")
    data = {"total": len(students)}
    for i, s in enumerate(students, 1):
        data[f"s_{i}"] = s.id
        
    txt = "\n".join(lines)
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()
    
    state = dp.fsm.get_context(
        bot=bot, 
        chat_id=callback.message.chat.id, 
        user_id=uid
    )
    await state.update_data(**data)
    await state.set_state(AddLesson.student)


@dp.callback_query(lambda c: c.data == "menu:list")
async def cb_list(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        result = await session.execute(q)
        lessons = result.scalars().all()
        
        q2 = select(Student)
        r2 = await session.execute(q2)
        students = r2.scalars().all()
        s_map = {s.id: s.full_name for s in students}
        
    if not lessons:
        kb = back_to_main()
        await callback.message.edit_text("📋 Занятий нет.", reply_markup=kb)
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
            
    txt = "\n".join(lines)
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:stats")
async def cb_stats(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Student)
        result = await session.execute(q)
        students = result.scalars().all()
        
        q2 = select(Lesson)
        r2 = await session.execute(q2)
        lessons = r2.scalars().all()
        
    now = now_msk()
    lines = ["📊 Статистика:\n"]
    lines.append(f"Учеников: {len(students)}")
    lines.append(f"Занятий: {len(lessons)}")
    
    done = [l for l in lessons if l.datetime_start < now]
    fut = [l for l in lessons if l.datetime_start >= now]
    lines.append(f"Проведено: {len(done)}")
    lines.append(f"Предстоит: {len(fut)}")
    
    txt = "\n".join(lines)
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id != TEACHER_ID)
        result = await session.execute(q)
        students = result.scalars().all()
        
    if not students:
        kb = back_to_main()
        await callback.message.edit_text("Учеников нет.", reply_markup=kb)
        await callback.answer()
        return
        
    lines = ["👥 Ученики:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
        
    txt = "\n".join(lines)
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    txt = (
        "🔍 Поиск ученика\n\n"
        "Напиши @username или имя:\n\n"
        "@alina или Алина"
    )
    kb = back_to_main()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()
    await state.set_state(FindStudent.query)


@dp.message(FindStudent.query)
async def find_query(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not is_teacher(uid):
        return
        
    q_in = message.text.strip()
    low = q_in.lower().lstrip("@")
    
    async with async_session() as session:
        q = select(Student)
        r = await session.execute(q)
        all_s = r.scalars().all()
        
    found = []
    for s in all_s:
        if s.tg_id == TEACHER_ID:
            continue
        nm = s.full_name.lower()
        un = (s.username or "").lower()
        if low in nm or low == un:
            found.append(s)
            
    if not found:
        kb = back_to_main()
        await message.answer("❌ Не найден.", reply_markup=kb)
        await state.clear()
        return
        
    if len(found) > 1:
        lines = ["🔍 Найдено несколько:\n"]
        for i, s in enumerate(found, 1):
            un = s.username or "—"
            lines.append(f"{i}. {s.full_name} @{un}")
        lines.append("\nУточни @username:")
        await message.answer("\n".join(lines))
        return
        
    s = found[0]
    await show_card(message, s)
    await state.clear()


async def show_card(message, student):
    async with async_session() as session:
        q = select(Lesson)
        q = q.where(Lesson.student_id == student.id)
        r = await session.execute(q)
        lessons = r.scalars().all()
        
    now = now_msk()
    done = len([l for l in lessons if l.datetime_start < now])
    fut = len([l for l in lessons if l.datetime_start >= now])
    paid = student.paid_lessons or 0
    left = paid - done
    un = student.username or "—"
    
    txt = (
        f"👤 {student.full_name}\n\n"
        f"@{un}\n"
        f"ID: {student.tg_id}\n\n"
        f"Проведено: {done}\n"
        f"Предстоит: {fut}\n"
        f"Оплачено: {paid}\n"
        f"Осталось: {left}"
    )
    kb = card_keyboard(student.id)
    await message.answer(txt, reply_markup=kb)


@dp.callback_query(lambda c: c.data.startswith("act:add:"))
async def cb_card_add(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    sid = int(callback.data.split(":")[2])
    async with async_session() as session:
        student = await session.get(Student, sid)
        
    if not student:
        await callback.answer("Не найден")
        return
        
    await state.update_data(sid=student.id, sname=student.full_name)
    txt = (
        f"Ученик: {student.full_name}\n\n"
        "Введи дату и время:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "15.10.2026 18:30"
    )
    await callback.message.edit_text(txt)
    await callback.answer()
    await state.set_state(AddLesson.dt)


@dp.callback_query(lambda c: c.data.startswith("act:pay:"))
async def cb_card_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    sid = int(callback.data.split(":")[2])
    async with async_session() as session:
        student = await session.get(Student, sid)
        
    if not student:
        await callback.answer("Не найден")
        return
        
    tg = student.tg_id
    txt = text_pay_after_button()
    kb = paid_button_keyboard()
    
    try:
        await bot.send_message(tg, txt, reply_markup=kb)
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
        return
        
    kb = back_to_main()
    await callback.message.edit_text("✅ Отправлено.", reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    txt = "💰 Оплата и напоминания\n\nЧто отправить?"
    kb = pay_menu()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data in ("pay:after", "pay:end"))
async def cb_pay_choose(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    mode = callback.data.split(":")[1]
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id != TEACHER_ID)
        r = await session.execute(q)
        students = r.scalars().all()
        
    if not students:
        kb = back_to_main("menu:pay")
        await callback.message.edit_text("Нет учеников.", reply_markup=kb)
        await callback.answer()
        return
        
    lines = ["👥 Кому:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
        
    lines.append(f"\nНомер 1–{len(students)} или @un")
    data = {"mode": mode, "total": len(students)}
    for i, s in enumerate(students, 1):
        data[f"st_{i}"] = s.tg_id
        
    await state.update_data(**data)
    await state.set_state(PayFlow.choosing_student)
    
    txt = "\n".join(lines)
    kb = back_to_main("menu:pay")
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.message(PayFlow.choosing_student)
async def pay_send(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not is_teacher(uid):
        return
        
    data = await state.get_data()
    total = data.get("total", 0)
    mode = data.get("mode")
    txt = message.text.strip()
    tg = None
    
    if txt.isdigit():
        num = int(txt)
        if 1 <= num <= total:
            tg = data.get(f"st_{num}")
            
    if tg is None:
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
                tg = s.tg_id
                break
                
    if tg is None:
        await message.answer("Не нашёл.")
        return
        
    if mode == "after":
        txt = text_pay_after_button()
    else:
        txt = text_pay_end_button()
        
    kb = paid_button_keyboard()
    try:
        await bot.send_message(tg, txt, reply_markup=kb)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await state.clear()
        return
        
    await state.clear()
    kb = back_to_main("menu:pay")
    await message.answer("✅ Отправлено.", reply_markup=kb)


@dp.callback_query(lambda c: c.data == "show:tariffs")
async def cb_show_tariffs(callback: CallbackQuery):
    txt = text_tariffs()
    kb = tariffs_keyboard()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("tar:"))
async def cb_tariff_chosen(callback: CallbackQuery):
    tar = callback.data.split(":")[1]
    tariffs = {
        "30_1": "30 мин, 1 раз — 2000 ₽",
        "30_2": "30 мин, 2 раза — 4000 ₽",
        "60_1": "60 мин, 1 раз — 4000 ₽",
        "60_2": "60 мин, 2 раза — 9000 ₽",
    }
    chosen = tariffs.get(tar, "?")
    u = callback.from_user
    
    txt = (
        "🔔 Заявка на абонемент\n\n"
        f"Ученик: {u.full_name}\n"
        f"@{u.username or '—'}\n"
        f"Тариф: {chosen}"
    )
    try:
        await bot.send_message(TEACHER_ID, txt)
    except Exception as e:
        logging.error(f"Ош: {e}")
        
    await callback.message.edit_text(
        "✅ Заявка отправлена!\n\nЯ свяжусь с тобой."
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(callback: CallbackQuery, state: FSMContext):
    txt = (
        "📸 Пришли, пожалуйста, "
        "скриншот оплаты.\n\n"
        "Он будет отправлен преподавателю."
    )
    kb = back_from_paid_keyboard()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()
    await state.set_state(PaymentProof.waiting_photo)


@dp.callback_query(lambda c: c.data == "paid:back")
async def cb_paid_back(callback: CallbackQuery, state: FSMContext):
    kb = back_to_main()
    await callback.message.edit_text("Ок, отменено.", reply_markup=kb)
    await callback.answer()
    await state.clear()


@dp.message(PaymentProof.waiting_photo)
async def receive_photo(message: types.Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, пришли именно фото.")
        return
        
    user = message.from_user
    photo = message.photo[-1]
    caption = (
        "💳 Оплата от ученика\n\n"
        f"Ученик: {user.full_name}\n"
        f"@{user.username or '—'}\n"
        f"ID: {user.id}"
    )
    try:
        await bot.send_photo(TEACHER_ID, photo.file_id, caption=caption)
    except Exception as e:
        logging.error(f"Ош: {e}")
        await message.answer("Ошибка отправки.")
        await state.clear()
        return
        
    kb = back_to_main()
    await message.answer(text_payment_received(), reply_markup=kb)
    await state.clear()


@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(callback: CallbackQuery, state: FSMContext):
    txt = text_transfer_ask()
    kb = transfer_cancel_keyboard()
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()
    await state.set_state(TransferFlow.reason)


@dp.callback_query(lambda c: c.data == "transfer:cancel")
async def cb_transfer_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(text_transfer_cancel())
    await callback.answer()
    await state.clear()


@dp.message(TransferFlow.reason)
async def transfer_reason(message: types.Message, state: FSMContext):
    user = message.from_user
    reason = message.text.strip()
    
    async with async_session() as session:
        q = select(Student)
        q = q.where(Student.tg_id == user.id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        
        if not student:
            await message.answer("Сначала /start")
            await state.clear()
            return
            
        now = now_msk()
        q2 = select(Lesson)
        q2 = q2.where(Lesson.student_id == student.id)
        q2 = q2.where(Lesson.datetime_start >= now)
        q2 = q2.order_by(Lesson.datetime_start)
        r2 = await session.execute(q2)
        lesson = r2.scalars().first()
        
    if lesson:
        dt = lesson.datetime_start
        les_info = f"{dt.strftime('%d.%m.%Y %H:%M')} — {lesson.title}"
    else:
        les_info = "—"
        
    un = user.username or "—"
    txt = (
        "🔄 Запрос на перенос\n\n"
        f"Ученик: {user.full_name}\n"
        f"@{un}\n"
        f"ID: {user.id}\n\n"
        f"Занятие: {les_info}\n"
        f"Причина: {reason}"
    )
    
    try:
        await bot.send_message(TEACHER_ID, txt)
    except Exception as e:
        logging.error(f"Ош: {e}")
        
    kb = back_to_main()
    await message.answer(text_transfer_sent(), reply_markup=kb)
    await state.clear()


@dp.callback_query(lambda c: c.data == "menu:reschedule")
async def cb_reschedule(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
        
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    
    if not future:
        kb = back_to_main()
        await callback.message.edit_text("Нет предстоящих.", reply_markup=kb)
        await callback.answer()
        return
        
    kb = lessons_action_keyboard(future, "resch")
    await callback.message.edit_text("🔄 Перенести:\n\nВыбери:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("resch:"))
async def cb_resch_choose(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        
    if not lesson:
        await callback.answer("Не найдено")
        return
        
    await state.update_data(lid=lid)
    dt = lesson.datetime_start
    txt = (
        f"Текущее: {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
        "Введи новую дату:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ"
    )
    await callback.message.edit_text(txt)
    await callback.answer()
    await state.set_state(RescheduleFlow.dt)


@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not is_teacher(uid):
        return
        
    try:
        txt = message.text.strip()
        new_dt = datetime.strptime(txt, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
        
    data = await state.get_data()
    lid = data.get("lid")
    
    async with async_session() as session:
        q = select(Lesson)
        q = q.where(Lesson.datetime_start == new_dt)
        q = q.where(Lesson.id != lid)
        r = await session.execute(q)
        existing = r.scalars().first()
        
        if existing:
            st = await session.get(Student, existing.student_id)
            name = st.full_name if st else "?"
            s = new_dt.strftime('%d.%m.%Y %H:%M')
            txt = (
                f"⚠️ На это время уже есть "
                f"занятие:\n\n{s} — {name}\n\n"
                "Выбери другое время."
            )
            await message.answer(txt)
            return
            
        lesson = await session.get(Lesson, lid)
        if not lesson:
            await message.answer("Не найдено.")
            await state.clear()
            return
            
        old_dt = lesson.datetime_start
        lesson.datetime_start = new_dt
        lesson.is_done = False
        await session.commit()
        
        q = select(Student)
        q = q.where(Student.id == lesson.student_id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        title = lesson.title
        
    if student:
        txt = (
            "🔄 Занятие перенесено!\n\n"
            f"Было: {old_dt.strftime('%d.%m %H:%M')}\n"
            f"Стало: {new_dt.strftime('%d.%m %H:%M')}\n"
            f"Тема: {title}"
        )
        try:
            await bot.send_message(student.tg_id, txt)
        except Exception as e:
            logging.error(f"Ош: {e}")
            
    kb = main_menu_teacher()
    await message.answer("✅ Перенесено!", reply_markup=kb)
    await state.clear()


@dp.callback_query(lambda c: c.data == "menu:delete")
async def cb_delete(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    async with async_session() as session:
        q = select(Lesson).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
        
    now = now_msk()
    future = [l for l in lessons if l.datetime_start >= now]
    
    if not future:
        kb = back_to_main()
        await callback.message.edit_text("Нет предстоящих.", reply_markup=kb)
        await callback.answer()
        return
        
    kb = lessons_action_keyboard(future, "del")
    await callback.message.edit_text("🗑 Удалить:\n\nВыбери:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("del:"))
async def cb_del_choose(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        
    if not lesson:
        await callback.answer("Не найдено")
        return
        
    dt = lesson.datetime_start
    txt = (
        f"Удалить занятие?\n\n"
        f"{dt.strftime('%d.%m.%Y %H:%M')}\n"
        f"{lesson.title}"
    )
    kb = confirm_delete_keyboard(lid)
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_del:"))
async def cb_del_confirm(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    lid = int(callback.data.split(":")[1])
    async with async_session() as session:
        lesson = await session.get(Lesson, lid)
        if not lesson:
            await callback.answer("Не найдено")
            return
            
        q = select(Student)
        q = q.where(Student.id == lesson.student_id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        
        title = lesson.title
        dt = lesson.datetime_start
        await session.delete(lesson)
        await session.commit()
        
    if student:
        txt = (
            "❌ Занятие отменено\n\n"
            f"{dt.strftime('%d.%m %H:%M')}\n"
            f"{title}"
        )
        try:
            await bot.send_message(student.tg_id, txt)
        except Exception as e:
            logging.error(f"Ош: {e}")
            
    kb = back_to_main()
    await callback.message.edit_text("✅ Удалено.", reply_markup=kb)
    await callback.answer()


async def check_duplicate_lesson(dt):
    async with async_session() as session:
        q = select(Lesson)
        q = q.where(Lesson.datetime_start == dt)
        r = await session.execute(q)
        existing = r.scalars().first()
        
        if not existing:
            return None
            
        st = await session.get(Student, existing.student_id)
        name = st.full_name if st else "?"
        s = dt.strftime('%d.%m.%Y %H:%M')
        return f"{s} — {name}"


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
    txt = (
        f"Ученик: {student.full_name}\n\n"
        "Введи дату и время:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "15.10.2026 18:30"
    )
    await message.answer(txt)
    await state.set_state(AddLesson.dt)


@dp.message(AddLesson.dt)
async def add_dt(message: types.Message, state: FSMContext):
    try:
        txt = message.text.strip()
        dt = datetime.strptime(txt, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
        
    dup = await check_duplicate_lesson(dt)
    if dup:
        txt = (
            f"⚠️ На это время уже есть "
            f"занятие:\n\n{dup}\n\n"
            "Выбери другое время."
        )
        await message.answer(txt)
        return
        
    await state.update_data(dt=dt)
    txt = "Название (или «-» = Итальянский):"
    await message.answer(txt)
    await state.set_state(AddLesson.title)


@dp.message(AddLesson.title)
async def add_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = message.text.strip()
    if title == "-":
        title = "Итальянский"
        
    async with async_session() as session:
        lesson = Lesson(
            student_id=data["sid"],
            datetime_start=data["dt"],
            title=title,
        )
        session.add(lesson)
        await session.commit()
        
    dt = data["dt"]
    txt = (
        "✅ Занятие добавлено!\n\n"
        f"Ученик: {data['sname']}\n"
        f"Дата: {dt.strftime('%d.%m.%Y %H:%M')}\n"
        f"Название: {title}"
    )
    kb = main_menu_teacher()
    await message.answer(txt, reply_markup=kb)
    await state.clear()


@dp.callback_query(lambda c: c.data.startswith("stdel:ask:"))
async def cb_stdel_ask(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    sid = int(callback.data.split(":")[2])
    async with async_session() as session:
        student = await session.get(Student, sid)
        
    if not student:
        await callback.answer("Не найден")
        return
        
    txt = (
        f"Удалить ученика?\n\n"
        f"{student.full_name}\n\n"
        f"⚠️ Все данные удалятся."
    )
    kb = confirm_delete_student_keyboard(sid)
    await callback.message.edit_text(txt, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("stdel:"))
async def cb_stdel_confirm(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
        
    sid = int(callback.data.split(":")[1])
    async with async_session() as session:
        student = await session.get(Student, sid)
        if not student:
            await callback.answer("Не найден")
            return
            
        name = student.full_name
        tg = student.tg_id
        await session.delete(student)
        await session.commit()
        
    kb = back_to_main()
    await callback.message.edit_text(f"✅ {name} удалён(а).", reply_markup=kb)
    await callback.answer()
    
    try:
        txt = (
            "❌ Ваш профиль удалён.\n"
            "Если ошибка — напишите мне."
        )
        await bot.send_message(tg, txt)
    except Exception:
        pass


async def health(request):
    return web.Response(text="OK")


async def on_startup(bot: Bot) -> None:
    await init_db()
    logging.info("БД готова")
    await bot.set_webhook(
        f"{URL}{PATH}",
        secret_token=SECRET,
        drop_pending_updates=True,
    )
    logging.info("Webhook ок")
    start_scheduler(bot)


app = web.Application()
handler = SimpleRequestHandler(
    dispatcher=dp,
    bot=bot,
    secret_token=SECRET,
)
handler.register(app, path=PATH)
app.router.add_get("/health", health)
setup_application(app, dp, bot=bot)
dp.startup.register(on_startup)

if __name__ == "__main__":
    print("Сервер запущен")
    web.run_app(app, host=HOST, port=PORT)