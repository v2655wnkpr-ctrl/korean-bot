import os

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

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
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