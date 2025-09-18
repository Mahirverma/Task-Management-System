# script.py
import sys
from getpass import getpass
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
from app.db import Base, engine, get_db
from app.models import user, task, task_log, time_log
from app.models.user import User, UserRole
from app.core.security import hash_password

def create_tables():
    print("📦 Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully.")

def create_superuser():
    db: Session = next(get_db())

    # Check if a superuser already exists
    existing = db.query(User).filter(User.role == UserRole.admin).first()
    if existing:
        print(f"⚠️  Superuser already exists: {existing.email}")
        return

    print("🛠 Creating superuser account...")
    username = input("Enter username: ").strip()
    email = input("Enter email: ").strip().lower()
    full_name = input("Enter full name: ").strip()
    password = getpass("Enter password: ")

    if not username or not email or not password:
        print("❌ Username, email, and password are required.")
        sys.exit(1)

    superuser = User(
        uuid = uuid.uuid4(),
        username=username,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name or None,
        role=UserRole.admin,
        created_by = None,
        create_at = datetime.now(),
        is_active=True
    )

    db.add(superuser)
    db.commit()
    print("✅ Superuser created successfully.")

if __name__ == "__main__":
    create_tables()
    create_superuser()