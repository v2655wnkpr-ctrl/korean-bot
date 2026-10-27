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
from models import Student, Lesson, Homework, HomeworkDone
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
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TEACHER_ID = 803167669

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

class SetTimezone(StatesGroup):
    choosing_tz = State()


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
        await callback.message.edit_text("Напиши, на сколько часов твое время отличается от Москвы (например, 7 для Владивостока, -1 для Калининграда):")
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
        await message.answer("Пожалуйста, напиши просто число (например, 7 или -1):")
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


# ... ДАЛЬШЕ ИДУТ ВСЕ ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (добавление занятий, оплата, календарь, домашки и т.д.).
# Они остаются точно такими же, как в прошлом полном файле bot.py.
# Если что-то потерялось, скажи, я скину конкретный кусок!