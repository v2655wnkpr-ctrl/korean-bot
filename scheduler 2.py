import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from sqlalchemy import select

from database import async_session
from models import Student, Lesson
from keyboards import transfer_keyboard


MSK = ZoneInfo("Europe/Moscow")
TEACHER_ID = 932503024

LESSON_LINK = (
    "https://telemost.yandex.ru/j/55769145881207"
)

scheduler = AsyncIOScheduler()


def now_msk() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


async def check_lessons(bot):
    now = now_msk()

    async with async_session() as session:
        q = select(Student)
        result = await session.execute(q)
        students = result.scalars().all()

        for student in students:
            hours = student.custom_hours_before
            if hours is None:
                hours = 2

            q2 = select(Lesson).where(
                Lesson.student_id == student.id
            )
            result2 = await session.execute(q2)
            lessons = result2.scalars().all()

            for lesson in lessons:
                diff = lesson.datetime_start - now
                mins = diff.total_seconds() / 60

                target = hours * 60
                if 0 <= target - mins <= 1:
                    await send_reminder(
                        bot, student, lesson
                    )

                if 0 <= 30 - mins <= 1:
                    await send_link(
                        bot, student, lesson
                    )

                if mins < -5 and not lesson.is_done:
                    lesson.is_done = True
                    await session.commit()
                    if student.paid_lessons > 0:
                        student.paid_lessons -= 1
                        await session.commit()
                        await check_paid(
                            bot, student, session
                        )


async def check_paid(bot, student, session):
    left = student.paid_lessons

    if left == 1:
        now = now_msk()
        last = student.last_payment_reminder
        if last is None or (now - last).days >= 1:
            text = (
                "💛 Осталось 1 занятие\n\n"
                "Пора продлить абонемент 🤍"
            )
            try:
                await bot.send_message(
                    student.tg_id, text
                )
            except Exception as e:
                logging.error(f"Ош: {e}")

            un = student.username or "—"
            t_text = (
                "⚠️ Осталось 1 занятие\n\n"
                f"{student.full_name}\n"
                f"@{un}"
            )
            try:
                await bot.send_message(
                    TEACHER_ID, t_text
                )
            except Exception as e:
                logging.error(f"Ош: {e}")

            student.last_payment_reminder = now
            await session.commit()


async def check_teacher(bot):
    now = now_msk()

    async with async_session() as session:
        q = select(Lesson)
        result = await session.execute(q)
        lessons = result.scalars().all()

        q2 = select(Student).where(
            Student.tg_id == TEACHER_ID
        )
        r2 = await session.execute(q2)
        teacher = r2.scalar_one_or_none()

        if not teacher:
            return

        hours = teacher.custom_hours_before
        if hours is None:
            hours = 2

        for lesson in lessons:
            diff = lesson.datetime_start - now
            mins = diff.total_seconds() / 60

            target = hours * 60
            if 0 <= target - mins <= 1:
                await send_teacher_rem(
                    bot, session, lesson
                )

            if 0 <= 5 - mins <= 1:
                await send_teacher_5(
                    bot, session, lesson
                )


async def send_teacher_rem(bot, session, lesson):
    q = select(Student).where(
        Student.id == lesson.student_id
    )
    r = await session.execute(q)
    student = r.scalar_one_or_none()
    name = student.full_name if student else "?"

    dt = lesson.datetime_start
    text = (
        "🔔 Напоминание (препод)\n\n"
        f"Сегодня в {dt.strftime('%H:%M')} "
        f"занятие с {name}\n"
        f"Тема: {lesson.title}"
    )
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_teacher_5(bot, session, lesson):
    q = select(Student).where(
        Student.id == lesson.student_id
    )
    r = await session.execute(q)
    student = r.scalar_one_or_none()
    name = student.full_name if student else "?"

    dt = lesson.datetime_start
    text = (
        "⏰ Через 5 минут занятие!\n\n"
        f"{name}, {dt.strftime('%H:%M')}\n"
        f"Тема: {lesson.title}\n\n"
        f"Ссылка: {LESSON_LINK}"
    )
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_reminder(bot, student, lesson):
    dt = lesson.datetime_start
    text = (
        "🔔 Напоминание!\n\n"
        f"Сегодня в {dt.strftime('%H:%M')} — "
        f"{lesson.title}\n\n"
        "Если не сможешь прийти — нажми "
        "кнопку ниже и напиши причину 👇"
    )
    try:
        await bot.send_message(
            student.tg_id,
            text,
            reply_markup=transfer_keyboard(),
        )
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_link(bot, student, lesson):
    dt = lesson.datetime_start
    text = (
        "🔗 Скоро занятие!\n\n"
        f"{lesson.title}, "
        f"{dt.strftime('%H:%M')}\n\n"
        f"Ссылка: {LESSON_LINK}"
    )
    try:
        await bot.send_message(student.tg_id, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


def start_scheduler(bot):
    scheduler.add_job(
        check_lessons,
        "interval",
        minutes=1,
        args=[bot],
    )
    scheduler.add_job(
        check_teacher,
        "interval",
        minutes=1,
        args=[bot],
    )
    scheduler.start()
    logging.info("Планировщик запущен")