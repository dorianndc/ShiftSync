from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.schemas import UserCreate

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/create-user")
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = User(
        email=payload.email,
        planning_login=payload.login,
        planning_password=payload.password
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message": "User créé",
        "user_id": user.id
    }