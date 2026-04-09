"""
Create or reset the admin user.

Usage (local):
    python create_admin.py

Usage (Heroku):
    heroku run python create_admin.py -a fss-newinventory
"""
from database import SessionLocal, engine, Base
import models
from auth import hash_password

Base.metadata.create_all(bind=engine)

EMAIL = "admin@foodstuff.store"
USERNAME = "admin"
PASSWORD = "admin123"
FULL_NAME = "System Administrator"

db = SessionLocal()
try:
    user = db.query(models.User).filter(models.User.username == USERNAME).first()
    if user:
        user.email = EMAIL
        user.hashed_password = hash_password(PASSWORD)
        user.role = models.UserRole.admin
        user.is_active = True
        db.commit()
        print(f"Updated existing admin → email: {EMAIL}")
    else:
        user = models.User(
            username=USERNAME,
            email=EMAIL,
            full_name=FULL_NAME,
            hashed_password=hash_password(PASSWORD),
            role=models.UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"Created admin → email: {EMAIL}")
finally:
    db.close()
