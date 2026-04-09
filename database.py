import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.getenv("DATABASE_URL", "sqlite:///./foodstuff.db")

# Heroku supplies postgres://, SQLAlchemy 1.4+ requires postgresql://
DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1)

_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_postgres = DATABASE_URL.startswith("postgresql")

connect_args = {}
engine_kwargs: dict = {}

if _is_sqlite:
    connect_args["check_same_thread"] = False

if _is_postgres:
    # Railway (and most managed Postgres) require SSL.
    # Only inject sslmode if not already in the URL.
    if "sslmode" not in DATABASE_URL:
        sep = "&" if "?" in DATABASE_URL else "?"
        DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

    # Connection pool tuning — Railway free tier limits concurrent connections.
    engine_kwargs.update(
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,      # drop stale connections automatically
        pool_recycle=1800,       # recycle connections every 30 minutes
    )

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
