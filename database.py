import os
import ssl

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        msg = "Нет DATABASE_URL"
        raise ValueError(msg)
    if url.startswith("postgres://"):
        url = url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )
    if url.startswith("postgresql://"):
        url = url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )
    return url


DATABASE_URL = get_db_url()

# Настройка SSL для ZevCloud и других удаленных баз
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "ssl": ssl_context,
        "timeout": 30,  # Даем базе 30 секунд на ответ
    },
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    from models import Student, Lesson
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )