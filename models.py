from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, index=True)
    full_name = Column(String)
    username = Column(String, nullable=True)
    timezone_offset = Column(Integer, default=0)
    paid_lessons = Column(Integer, default=0)
    
    hw_reminder_enabled = Column(Boolean, default=True)
    lesson_reminder_hours = Column(Integer, default=2)

    lessons = relationship("Lesson", back_populates="student")
    hw_done = relationship("HomeworkDone", back_populates="student")
    hw_submissions = relationship("HomeworkSubmission", back_populates="student")


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    datetime_start = Column(DateTime)
    title = Column(String, default="Корейский")

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
    text = Column(String)
    media_type = Column(String, nullable=True)
    media_id = Column(String, nullable=True)
    chat_id = Column(BigInteger, nullable=True)
    deadline = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class HomeworkDone(Base):
    __tablename__ = "homework_done"

    id = Column(Integer, primary_key=True, index=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"))
    student_id = Column(Integer, ForeignKey("students.id"))

    student = relationship("Student", back_populates="hw_done")


class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"

    id = Column(Integer, primary_key=True, index=True)
    homework_id = Column(Integer, ForeignKey("homeworks.id"))
    student_id = Column(Integer, ForeignKey("students.id"))
    media_type = Column(String)
    media_id = Column(String)

    student = relationship("Student", back_populates="hw_submissions") 