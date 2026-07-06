import os
from typing import Generator

from app.core.platform_patch import patch_windows_platform_machine

patch_windows_platform_machine()

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _sqlite_path_from_url(url: str) -> str:
    if not url.startswith("sqlite:///"):
        return ""
    return url.replace("sqlite:///", "", 1)


sqlite_path = _sqlite_path_from_url(settings.database_url)
if sqlite_path:
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        _upgrade_sqlite_schema()


def _upgrade_sqlite_schema() -> None:
    required_columns = {
        "gmail_accounts": {
            "auth_type": "VARCHAR(40) NOT NULL DEFAULT 'app_password'",
            "encrypted_app_password": "TEXT",
            "proxy_mode": "VARCHAR(20) NOT NULL DEFAULT 'auto'",
        }
    }
    with engine.begin() as connection:
        for table_name, columns in required_columns.items():
            existing = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(%s)" % table_name).fetchall()
            }
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    connection.exec_driver_sql("ALTER TABLE %s ADD COLUMN %s %s" % (table_name, column_name, ddl))
