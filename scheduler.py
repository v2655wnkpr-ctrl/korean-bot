import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from database import async_session
from models import Lesson, Student, LessonSlot, Homework, HomeworkDone

scheduler = AsyncIOScheduler()

def now_msk() -> datetime:
    # Возвращает текущее время по Москве (UTC+3)
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)

async def check_lessons(bot):
    """Проверяет занятия и рассылает напоминания"""
    now = now_msk()
    async with async_session() as session:
        # Получаем занятия на ближайшие 24 часа
        q = select(Lesson).where(Lesson.datetime_start >= now, Lesson.datetime_start <= now + timedelta(hours=24))
        r = await session.execute(q)
        lessons = r.scalars().all()
        
        for lesson in lessons:
            q_st = select(Student).where(Student.id == lesson.student_id)
            r_st = await session.execute(q_st)
            st = r_st.scalar_one_or_none()
            if not st: continue
            
            # Настройки напоминания ученика (по умолчанию 2 часа)
            remind_hours = st.lesson_reminder_hours if st.lesson_reminder_hours is not None else 2
            
            # Учитываем часовой пояс ученика
            local_lesson_time = lesson.datetime_start + timedelta(hours=st.timezone_offset)
            local_now = now + timedelta(hours=st.timezone_offset)
            
            diff_minutes = (local_lesson_time - local_now).total_seconds() / 60
            
            # Напоминание за N часов (проверяем с точностью до минуты)
            if int(diff_minutes) == int(remind_hours * 60):
                text = f"🔔 Напоминание: у тебя занятие через {remind_hours} ч.\n\n📅 {local_lesson_time.strftime('%d.%m %H:%M')}\n📚 {lesson.title}"
                try:
                    await bot.send_message(st.tg_id, text)
                except Exception:
                    pass
                    
            # Ссылка на урок за 30 минут
            if int(diff_minutes) == 30:
                text = f"🔗 Скоро урок! Подключайся:\n\n📅 {local_lesson_time.strftime('%H:%M')}\nСсылка: (тут будет твоя ссылка)"
                try:
                    await bot.send_message(st.tg_id, text)
                except Exception:
                    pass

async def check_homework_reminders(bot):
    """Проверяет невыполненные ДЗ и напоминает раз в день"""
    now = now_msk()
    # Отправляем напоминания только в 18:00
    if now.hour != 18:
        return

    async with async_session() as session:
        # Берем всех учеников, у кого включены напоминания
        q_st = select(Student).where(
            Student.tg_id != 803167669, 
            Student.hw_reminder_enabled == True
        )
        r_st = await session.execute(q_st)
        students = r_st.scalars().all()
        
        for st in students:
            # Ищем все ДЗ
            q_hw = select(Homework)
            r_hw = await session.execute(q_hw)
            all_hws = r_hw.scalars().all()
            
            uncompleted = []
            for hw in all_hws:
                q_done = select(HomeworkDone).where(
                    HomeworkDone.homework_id == hw.id,
                    HomeworkDone.student_id == st.id
                )
                r_done = await session.execute(q_done)
                if not r_done.scalar_one_or_none():
                    uncompleted.append(hw.title)

            if uncompleted:
                hw_list = "\n".join([f"• {title}" for title in uncompleted])
                text = (
                    f"📚 <b>Напоминание о домашнем задании!</b>\n\n"
                    f"Ты еще не сдал:\n{hw_list}\n\n"
                    f"Зайди в раздел «Домашки», чтобы выполнить их. 👇"
                )
                try:
                    await bot.send_message(st.tg_id, text, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Ошибка отправки ДЗ {st.tg_id}: {e}")

def start_scheduler(bot):
    scheduler.add_job(check_lessons, 'interval', minutes=1, args=[bot])
    scheduler.add_job(check_homework_reminders, 'interval', minutes=1, args=[bot])
    scheduler.start()
    logging.info("Планировщик запущен")