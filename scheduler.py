import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from database import async_session
from models import Student, Lesson, Homework, HomeworkDone


MSK = ZoneInfo("Europe/Moscow")
TEACHER_ID = 803167669
LESSON_LINK = "ССЫЛКА_НА_СОЗВОН"

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
            hours = student.custom_hours_before or 2
            q2 = select(Lesson).where(Lesson.student_id == student.id)
            result2 = await session.execute(q2)
            lessons = result2.scalars().all()

            for lesson in lessons:
                diff = lesson.datetime_start - now
                mins = diff.total_seconds() / 60
                target = hours * 60
                if 0 <= target - mins <= 1:
                    await send_reminder(bot, student, lesson)
                if 0 <= 30 - mins <= 1:
                    await send_link(bot, student, lesson)
                if mins < -5 and not lesson.is_done:
                    lesson.is_done = True
                    await session.commit()
                    if student.paid_lessons > 0:
                        student.paid_lessons -= 1
                        await session.commit()
                        await check_paid(bot, student, session)


async def check_paid(bot, student, session):
    left = student.paid_lessons
    if left == 1:
        now = now_msk()
        last = student.last_payment_reminder
        if last is None or (now - last).days >= 1:
            text = "💛 Осталось 1 занятие\n\nПора продлить абонемент 🤍"
            try:
                await bot.send_message(student.tg_id, text)
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

        q2 = select(Student).where(Student.tg_id == TEACHER_ID)
        r2 = await session.execute(q2)
        teacher = r2.scalar_one_or_none()

        if not teacher:
            return

        hours = teacher.custom_hours_before or 2
        for lesson in lessons:
            diff = lesson.datetime_start - now
            mins = diff.total_seconds() / 60
            target = hours * 60
            if 0 <= target - mins <= 1:
                await send_teacher_rem(bot, session, lesson)
            if 0 <= 5 - mins <= 1:
                await send_teacher_5(bot, session, lesson)


async def check_homework(bot):
    now = now_msk()
    async with async_session() as session:
        q = select(Student)
        result = await session.execute(q)
        students = result.scalars().all()

        for student in students:
            if not student.hw_reminder_enabled:
                continue
            
            days = student.hw_reminder_days or 1
            
            q2 = select(Homework).where(Homework.deadline != None, Homework.deadline > now)
            result2 = await session.execute(q2)
            homeworks = result2.scalars().all()
            
            for hw in homeworks:
                q3 = select(HomeworkDone).where(HomeworkDone.homework_id == hw.id, HomeworkDone.student_id == student.id)
                r3 = await session.execute(q3)
                done = r3.scalar_one_or_none()
                
                if done:
                    continue
                
                diff = hw.deadline - now
                if 0 <= (diff.total_seconds() / 86400) - days <= 0.01:
                    text = f"📚 Напоминание о ДЗ!\n\nТема: {hw.title}\n\nНе забудь сдать до {hw.deadline.strftime('%d.%m %H:%M')}!"
                    try:
                        await bot.send_message(student.tg_id, text)
                    except Exception as e:
                        logging.error(f"Ош: {e}")


async def send_teacher_rem(bot, session, lesson):
    q = select(Student).where(Student.id == lesson.student_id)
    r = await session.execute(q)
    student = r.scalar_one_or_none()
    name = student.full_name if student else "?"
    dt = lesson.datetime_start
    text = f"🔔 Напоминание (препод)\n\nСегодня в {dt.strftime('%H:%M')} занятие с {name}\nТема: {lesson.title}"
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_teacher_5(bot, session, lesson):
    q = select(Student).where(Student.id == lesson.student_id)
    r = await session.execute(q)
    student = r.scalar_one_or_none()
    name = student.full_name if student else "?"
    dt = lesson.datetime_start
    text = f"⏰ Через 5 минут занятие!\n\n{name}, {dt.strftime('%H:%M')}\nТема: {lesson.title}\n\nСсылка: {LESSON_LINK}"
    try:
        await bot.send_message(TEACHER_ID, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_reminder(bot, student, lesson):
    dt = lesson.datetime_start
    text = f"🔔 Напоминание!\n\nСегодня в {dt.strftime('%H:%M')} — {lesson.title}"
    try:
        await bot.send_message(student.tg_id, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


async def send_link(bot, student, lesson):
    dt = lesson.datetime_start
    text = f"🔗 Скоро занятие!\n\n{lesson.title}, {dt.strftime('%H:%M')}\n\nСсылка: {LESSON_LINK}"
    try:
        await bot.send_message(student.tg_id, text)
    except Exception as e:
        logging.error(f"Ош: {e}")


def start_scheduler(bot):
    scheduler.add_job(check_lessons, "interval", minutes=1, args=[bot])
    scheduler.add_job(check_teacher, "interval", minutes=1, args=[bot])
    scheduler.add_job(check_homework, "interval", hours=1, args=[bot])
    scheduler.start()
    logging.info("Планировщик запущен")