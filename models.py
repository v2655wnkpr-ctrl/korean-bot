from datetime import datetime
from sqlalchemy import (
    BigInteger, String, DateTime, ForeignKey,
    Integer, Boolean, Text,
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship,
)

from database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone_offset: Mapped[int] = mapped_column(Integer, default=0)

    custom_hours_before: Mapped[int] = mapped_column(Integer, default=2)
    paid_lessons: Mapped[int] = mapped_column(Integer, default=0)
    last_payment_reminder: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    hw_reminder_days: Mapped[int] = mapped_column(Integer, default=1)
    hw_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    lessons: Mapped[list["Lesson"]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    datetime_start: Mapped[datetime] = mapped_column(DateTime)
    title: Mapped[str] = mapped_column(String(200), default="Корейский")
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)

    student: Mapped["Student"] = relationship(back_populates="lessons")


class Homework(Base):
    __tablename__ = "homeworks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class HomeworkDone(Base):
    __tablename__ = "homework_done"
    id: Mapped[int] = mapped_column(primary_key=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("homeworks.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    done_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class LessonSlot(Base):
    __tablename__ = "lesson_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(BigInteger)
    datetime_start: Mapped[datetime] = mapped_column(DateTime)
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)


class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("homeworks.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    