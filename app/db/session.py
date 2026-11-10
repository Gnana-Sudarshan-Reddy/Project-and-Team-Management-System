"""Create the database engine and provide sessions to API requests."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
# SQLite needs this option for its connections to be shared across test threads.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:  # SQLite ignores foreign keys unless enabled per connection

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _):
        """Enable SQLite foreign-key checks for every new connection."""
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """Provide one database session per request and always close it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
