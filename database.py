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
        raise ValueError("Нет DATABASE_URL")
    # Замена префикса для asyncpg
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

DATABASE_URL = get_db_url()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # Для внутренней сети SSL не нужен, но добавляем таймауты для надежности
    connect_args={
        "timeout": 60,
        "command_timeout": 60,
    },
    pool_pre_ping=True,
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
        await conn.run_sync(Base.metadata.create_all)