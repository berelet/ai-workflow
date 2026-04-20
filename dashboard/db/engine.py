import os
from urllib.parse import quote_plus
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


def _build_url() -> str:
    host = os.getenv("PGSQL_AIWORKFLOW_HOST", "localhost")
    port = os.getenv("PGSQL_AIWORKFLOW_PORT", "5432")
    db = os.getenv("PGSQL_AIWORKFLOW_DB", "aiworkflow")
    user = os.getenv("PGSQL_AIWORKFLOW_USER", "aiworkflow_app")
    password = quote_plus(os.getenv("PGSQL_AIWORKFLOW_PASSWORD", ""))
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _build_url()

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    connect_args={
        "timeout": 10,
        "command_timeout": 30,
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency that yields an async DB session."""
    async with async_session() as session:
        yield session
