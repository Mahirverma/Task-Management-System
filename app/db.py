
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings


# ---------- SQLAlchemy Setup ----------
engine = create_engine(settings.database_url, echo=True, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ---------- Dependency ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()