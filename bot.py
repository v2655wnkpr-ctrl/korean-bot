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
    InlineKeyboardButton,
    CallbackQuery,
)
from dotenv import load_dotenv
from sqlalchemy import select

from database import init_db, async_session
from models import (
    Student,
    Lesson,
    Homework,
    HomeworkDone,
)
from scheduler import start_scheduler, now_msk
from texts import (
    text_pay_after,
    text_pay_end,
    text_tariffs,
    text_help,
    hours_text,
    text_pay_after_button,
    text_pay_end_button,
    text_payment_received,
    text_welcome,
    text_transfer_ask,
    text_transfer_sent,
    text_transfer_cancel,
    text_hw_add_deadline,
    text_hw_reminder_settings,
    text_hw_reminder_off,
    text_hw_reminder_on,
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
    hw_menu_teacher,
    hw_reminder_keyboard,
    TEACHER_LINK,
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


def is_teacher(uid: int) -> bool:
    return uid == TEACHER_ID


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    uid = user.id
    is_new = False

    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
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
                text = (
                    "🆕 Новый ученик!\n\n"
                    f"{user.full_name}\n"
                    f"@{un}\n"
                    f"ID: {uid}"
                )
                try:
                    await bot.send_message(TEACHER_ID, text)
                except Exception as e:
                    logging.error(f"Ош: {e}")

    if is_new and not is_teacher(uid):
        await message.answer(text_welcome(), reply_markup=main_menu_student())
        return

    if is_teacher(uid):
        text = "👋 Привет, преподаватель!\n\nВыбери действие:"
        kb = main_menu_teacher()
    else:
        text = f"👋 Привет, {user.full_name}!\n\nВыбери действие:"
        kb = main_menu_student()

    await message.answer(text, reply_markup=kb)


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
        q = select(Student).where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()

    if not student:
        await message.answer("Сначала /start")
        return

    hours = student.custom_hours_before or 2
    text = f"⚙️ Напоминания\n\nСейчас {hours_text(hours)}.\n\nВыбери:"
    await message.answer(text, reply_markup=hours_keyboard())


@dp.message(Command("set_paid"))
async def cmd_set_paid(message: types.Message):
    uid = message.from_user.id
    if not is_teacher(uid):
        await message.answer("Только для препода.")
        return
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
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


# ---------- Меню (callbacks) ----------

@dp.callback_query(lambda c: c.data == "menu:main")
async def cb_main(callback: CallbackQuery):
    uid = callback.from_user.id
    if is_teacher(uid):
        kb = main_menu_teacher()
    else:
        kb = main_menu_student()
    await callback.message.edit_text("Главное меню:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(text_help(), reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:settings")
async def cb_settings(callback: CallbackQuery):
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
    if not student:
        await callback.answer("Сначала /start")
        return
    hours = student.custom_hours_before or 2
    text = f"⚙️ Напоминания\n\nСейчас {hours_text(hours)}.\n\nВыбери:"
    await callback.message.edit_text(text, reply_markup=hours_keyboard())
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("h:"))
async def cb_hours(callback: CallbackQuery):
    hours = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
        if student:
            student.custom_hours_before = hours
            await session.commit()
    text = f"✅ Готово!\n\nНапомню {hours_text(hours)}."
    await callback.message.edit_text(text, reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:lessons")
async def cb_lessons(callback: CallbackQuery):
    uid = callback.from_user.id
    async with async_session() as session:
        q = select(Student).where(Student.tg_id == uid)
        result = await session.execute(q)
        student = result.scalar_one_or_none()
        if not student:
            await callback.answer("Сначала /start")
            return
        q2 = select(Lesson).where(Lesson.student_id == student.id).order_by(Lesson.datetime_start)
        r2 = await session.execute(q2)
        lessons = r2.scalars().all()
    if not lessons:
        await callback.message.edit_text("📅 Пока нет занятий.", reply_markup=back_to_main())
        await callback.answer()
        return
    now = now_msk()
    lines = ["📅 Твои занятия:\n"]
    for les in lessons:
        dt = les.datetime_start
        mark = "✓" if dt < now else "•"
        s = dt.strftime("%d.%m %H:%M")
        lines.append(f"{mark} {s} — {les.title}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:add")
async def cb_add(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
        result = await session.execute(q)
        students = result.scalars().all()
    if not students:
        await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main())
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
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    await callback.answer()
    state = dp.fsm.get_context(bot=bot, chat_id=callback.message.chat.id, user_id=uid)
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
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "menu:students")
async def cb_students(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
        result = await session.execute(q)
        students = result.scalars().all()
    if not students:
        await callback.message.edit_text("Учеников нет.", reply_markup=back_to_main())
        await callback.answer()
        return
    lines = ["👥 Ученики:\n"]
    for i, s in enumerate(students, 1):
        un = s.username or "—"
        lines.append(f"{i}. {s.full_name} @{un}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main())
    await callback.answer()


# ---------- Поиск ученика ----------

@dp.callback_query(lambda c: c.data == "menu:find")
async def cb_find(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    text = "🔍 Поиск ученика\n\nНапиши @username или имя:\n\n@alina или Алина"
    await callback.message.edit_text(text, reply_markup=back_to_main())
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
        await message.answer("❌ Не найден.", reply_markup=back_to_main())
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
        q = select(Lesson).where(Lesson.student_id == student.id)
        r = await session.execute(q)
        lessons = r.scalars().all()
    now = now_msk()
    done = len([l for l in lessons if l.datetime_start < now])
    fut = len([l for l in lessons if l.datetime_start >= now])
    paid = student.paid_lessons or 0
    left = paid - done
    un = student.username or "—"
    text = (
        f"👤 {student.full_name}\n\n"
        f"@{un}\n"
        f"ID: {student.tg_id}\n\n"
        f"Проведено: {done}\n"
        f"Предстоит: {fut}\n"
        f"Оплачено: {paid}\n"
        f"Осталось: {left}"
    )
    kb = card_keyboard(student.id)
    await message.answer(text, reply_markup=kb)


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
    text = (
        f"Ученик: {student.full_name}\n\n"
        "Введи дату и время:\n"
        "ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "15.10.2026 18:30"
    )
    await callback.message.edit_text(text)
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
    text = text_pay_after_button()
    kb = paid_button_keyboard()
    try:
        await bot.send_message(tg, text, reply_markup=kb)
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.edit_text("✅ Отправлено.", reply_markup=back_to_main())
    await callback.answer()


# ---------- Оплата ----------

@dp.callback_query(lambda c: c.data == "menu:pay")
async def cb_pay(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("💰 Оплата и напоминания\n\nЧто отправить?", reply_markup=pay_menu())
    await callback.answer()


@dp.callback_query(lambda c: c.data in ("pay:after", "pay:end"))
async def cb_pay_choose(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not is_teacher(uid):
        await callback.answer("Нет доступа")
        return
    mode = callback.data.split(":")[1]
    async with async_session() as session:
        q = select(Student).where(Student.tg_id != TEACHER_ID)
        r = await session.execute(q)
        students = r.scalars().all()
    if not students:
        await callback.message.edit_text("Нет учеников.", reply_markup=back_to_main("menu:pay"))
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
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:pay"))
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
        text = text_pay_after_button()
    else:
        text = text_pay_end_button()
    kb = paid_button_keyboard()
    try:
        await bot.send_message(tg, text, reply_markup=kb)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await state.clear()
        return
    await state.clear()
    await message.answer("✅ Отправлено.", reply_markup=back_to_main("menu:pay"))


@dp.callback_query(lambda c: c.data == "show:tariffs")
async def cb_show_tariffs(callback: CallbackQuery):
    await callback.message.edit_text(text_tariffs(), reply_markup=tariffs_keyboard())
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
    text = (
        "🔔 Заявка на абонемент\n\n"
        f"Ученик: {u.full_name}\n"
        f"@{u.username or '—'}\n"
        f"Тариф: {chosen}"
    )
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")
    await callback.message.edit_text("✅ Заявка отправлена!\n\nЯ свяжусь с тобой.")
    await callback.answer()


# ---------- Я оплатил ----------

@dp.callback_query(lambda c: c.data == "paid:click")
async def cb_paid_click(callback: CallbackQuery, state: FSMContext):
    text = (
        "📸 Пришли, пожалуйста, "
        "скриншот оплаты.\n\n"
        "Он будет отправлен преподавателю."
    )
    await callback.message.edit_text(text, reply_markup=back_from_paid_keyboard())
    await callback.answer()
    await state.set_state(PaymentProof.waiting_photo)


@dp.callback_query(lambda c: c.data == "paid:back")
async def cb_paid_back(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Ок, отменено.", reply_markup=back_to_main())
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
    await message.answer(text_payment_received(), reply_markup=back_to_main())
    await state.clear()


# ---------- Переносы ----------

@dp.callback_query(lambda c: c.data == "transfer:click")
async def cb_transfer_click(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(text_transfer_ask(), reply_markup=transfer_cancel_keyboard())
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
        q = select(Student).where(Student.tg_id == user.id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        if not student:
            await message.answer("Сначала /start")
            await state.clear()
            return
        now = now_msk()
        q2 = select(Lesson).where(Lesson.student_id == student.id).where(Lesson.datetime_start >= now).order_by(Lesson.datetime_start)
        r2 = await session.execute(q2)
        lesson = r2.scalars().first()
    if lesson:
        dt = lesson.datetime_start
        les_info = f"{dt.strftime('%d.%m.%Y %H:%M')} — {lesson.title}"
    else:
        les_info = "—"
    un = user.username or "—"
    text = (
        "🔄 Запрос на перенос\n\n"
        f"Ученик: {user.full_name}\n"
        f"@{un}\n"
        f"ID: {user.id}\n\n"
        f"Занятие: {les_info}\n"
        f"Причина: {reason}"
    )
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")
    await message.answer(text_transfer_sent(), reply_markup=back_to_main())
    await state.clear()


# ---------- Перенос преподавателем ----------

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
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        await callback.answer()
        return
    await callback.message.edit_text("🔄 Перенести занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "resch"))
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
    text = f"Текущее: {dt.strftime('%d.%m.%Y %H:%M')}\n\nВведи новую дату и время:\nДД.ММ.ГГГГ ЧЧ:ММ"
    await callback.message.edit_text(text)
    await callback.answer()
    await state.set_state(RescheduleFlow.dt)


@dp.message(RescheduleFlow.dt)
async def resch_apply(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not is_teacher(uid):
        return
    try:
        new_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
    data = await state.get_data()
    lid = data.get("lid")
    async with async_session() as session:
        q = select(Lesson).where(Lesson.datetime_start == new_dt, Lesson.id != lid)
        r = await session.execute(q)
        existing = r.scalars().first()
        if existing:
            st = await session.get(Student, existing.student_id)
            name = st.full_name if st else "?"
            s = new_dt.strftime('%d.%m.%Y %H:%M')
            txt = f"⚠️ На это время уже есть занятие:\n\n{s} — {name}\n\nВыбери другое время."
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
        q = select(Student).where(Student.id == lesson.student_id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        title = lesson.title
    if student:
        text = (
            "🔄 Занятие перенесено!\n\n"
            f"Было: {old_dt.strftime('%d.%m %H:%M')}\n"
            f"Стало: {new_dt.strftime('%d.%m %H:%M')}\n"
            f"Тема: {title}"
        )
        try:
            await bot.send_message(student.tg_id, text)
        except Exception as e:
            logging.error(f"Ош: {e}")
    await message.answer("✅ Перенесено!", reply_markup=main_menu_teacher())
    await state.clear()


# ---------- Удаление преподавателем ----------

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
        await callback.message.edit_text("Нет предстоящих занятий.", reply_markup=back_to_main())
        await callback.answer()
        return
    await callback.message.edit_text("🗑 Удалить занятие\n\nВыбери:", reply_markup=lessons_action_keyboard(future, "del"))
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
    text = f"Удалить занятие?\n\n{dt.strftime('%d.%m.%Y %H:%M')}\n{lesson.title}"
    await callback.message.edit_text(text, reply_markup=confirm_delete_keyboard(lid))
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
        q = select(Student).where(Student.id == lesson.student_id)
        r = await session.execute(q)
        student = r.scalar_one_or_none()
        title = lesson.title
        dt = lesson.datetime_start
        await session.delete(lesson)
        await session.commit()
    if student:
        text = f"❌ Занятие отменено\n\n{dt.strftime('%d.%m %H:%M')}\n{title}"
        try:
            await bot.send_message(student.tg_id, text)
        except Exception as e:
            logging.error(f"Ош: {e}")
    await callback.message.edit_text("✅ Удалено.", reply_markup=back_to_main())
    await callback.answer()


# ---------- Добавление занятия ----------

async def check_duplicate_lesson(dt):
    async with async_session() as session:
        q = select(Lesson).where(Lesson.datetime_start == dt)
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
    text = f"Ученик: {student.full_name}\n\nВведи дату и время:\nДД.ММ.ГГГГ ЧЧ:ММ\n15.10.2026 18:30"
    await message.answer(text)
    await state.set_state(AddLesson.dt)


@dp.message(AddLesson.dt)
async def add_dt(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Формат: 15.10.2026 18:30")
        return
    dup = await check_duplicate_lesson(dt)
    if dup:
        txt = f"⚠️ На это время уже есть занятие:\n\n{dup}\n\nВыбери другое время."
        await message.answer(txt)
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
        lesson = Lesson(student_id=data["sid"], datetime_start=data["dt"], title=title)
        session.add(lesson)
        await session.commit()
    dt = data["dt"]
    text = f"✅ Занятие добавлено!\n\nУченик: {data['sname']}\nДата: {dt.strftime('%d.%m.%Y %H:%M')}\nНазвание: {title}"
    await message.answer(text, reply_markup=main_menu_teacher())
    await state.clear()


# ---------- Удаление ученика ----------

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
    text = f"Удалить ученика?\n\n{student.full_name}\n\n⚠️ Все данные удалятся."
    kb = confirm_delete_student_keyboard(sid)
    await callback.message.edit_text(text, reply_markup=kb)
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
    await callback.message.edit_text(f"✅ {name} удалён(а).", reply_markup=back_to_main())
    await callback.answer()
    try:
        txt = "❌ Ваш профиль удалён.\nЕсли ошибка — напишите мне."
        await bot.send_message(tg, txt)
    except Exception:
        pass


# ---------- Webhook ----------
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
    
    days = {l.datetime_start.day for l in lessons if l.datetime_start.month == month}
    kb = calendar_keyboard(year, month, days)
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("cal:nav:"))
async def cb_cal_nav(callback: CallbackQuery):
    _, _, y, m = callback.data.split(":")
    y, m = int(y), int(m)
    if m < 1:
        m = 12
        y -= 1
    elif m > 12:
        m = 1
        y += 1
    callback.data = f"cal:init:{y}:{m}"
    await cb_calendar_init(callback)

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
    
    days = {l.datetime_start.day for l in lessons if l.datetime_start.month == m}
    kb = calendar_keyboard(y, m, days)
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=kb)
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
        q = select(Lesson).where(
            Lesson.datetime_start >= dt_start,
            Lesson.datetime_start <= dt_end
        ).order_by(Lesson.datetime_start)
        r = await session.execute(q)
        lessons = r.scalars().all()
    
    if not lessons:
        await callback.message.edit_text(f"📅 {d}.{m:02d}.{y}\n\nЗанятий нет.", reply_markup=back_to_main("menu:calendar"))
        await callback.answer()
        return
    
    lines = [f"📅 {d}.{m:02d}.{y}\n"]
    for l in lessons:
        lines.append(f"• {l.datetime_start.strftime('%H:%M')} — {l.title}")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_main("menu:calendar"))
    await callback.answer()
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
    
    days = {l.datetime_start.day for l in lessons if l.datetime_start.month == month}
    kb = calendar_keyboard(year, month, days)
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=kb)
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
    
    days = {l.datetime_start.day for l in lessons if l.datetime_start.month == m}
    kb = calendar_keyboard(y, m, days)
    await callback.message.edit_text("📅 Твой календарь:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cal:ignore")
async def cb_cal_ignore(callback: CallbackQuery):
    await callback.answer()
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