from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True)
    full_name = Column(String)
    username = Column(String, nullable=True)
    
    custom_name = Column(String, nullable=True) # ДОБАВЛЕНО: кастомное имя ученика
    timezone_offset = Column(Integer, default=0)
    paid_lessons = Column(Integer, default=0)
    
    custom_hours_before = Column(Integer, default=2) # ИСПРАВЛЕНО: под код bot.py
    last_payment_reminder = Column(DateTime, nullable=True) # ДОБАВЛЕНО: под код bot.py
    
    hw_reminder_enabled = Column(Boolean, default=True)
    hw_reminder_days = Column(Integer, default=1) # ДОБАВЛЕНО: под код bot.py

    lessons = relationship("Lesson", back_populates="student")
    hw_done = relationship("HomeworkDone", back_populates="student")

class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    datetime_start = Column(DateTime)
    title = Column(String, default="Корейский")
    is_done = Column(Boolean, default=False)

    student = relationship("Student", back_populates="lessons")

class LessonSlot(Base):
    __tablename__ = "lesson_slots"

    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(BigInteger) 
    datetime_start = Column(DateTime)
    is_booked = Column(Boolean, default=False)

class Homework(Base):
    __tablename__ = "homeworks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    text = Column(Text) # Лучше Text вместо String для длинных ДЗ
    target_student_id = Column(Integer, ForeignKey("students.id"), nullable=True) # ДОБАВЛЕНО: кому назначено
    deadline = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class HomeworkMedia(Base):
    __tablename__ = "homework_media"
    
    id = Column(Integer, primary_key=True, index=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"))
    media_type = Column(String, nullable=True)  # "photo" или "video"
    media_id = Column(String, nullable=True)    # file_id телеграма
    chat_id = Column(BigInteger, nullable=True)

class HomeworkDone(Base):
    __tablename__ = "homework_done"

    id = Column(Integer, primary_key=True, index=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"))
    student_id = Column(Integer, ForeignKey("students.id"))

    student = relationship("Student", back_populates="hw_done")