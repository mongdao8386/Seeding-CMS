from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from seeding.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    # Co y KHONG bat pool_pre_ping: voi engine async, cu ping luc checkout co the
    # xay ra ngoai greenlet (vd luc interpreter shutdown) va nem MissingGreenlet,
    # che mat loi that. Neu can chong ket noi chet thi dat pool_recycle thay vi ping.
    pool_recycle=1800,
    # Worker giu ket noi lau; pool nho de khong chiem het slot cua Postgres.
    pool_size=5,
    max_overflow=5,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency cho FastAPI."""
    async with SessionLocal() as session:
        yield session
