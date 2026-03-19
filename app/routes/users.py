from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.schemas import UserCreate
from app.services.ics_service import generate_ics_for_user

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/create-user")
def create_user(payload: UserCreate, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.email == payload.email).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    user = User(
        email=payload.email,
        planning_login=payload.login,
        planning_password=payload.password
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # 🔥 génération ICS
    ics_path = generate_ics_for_user(user)
    user.ics_path = ics_path
    db.commit()

    return {
        "message": "User créé",
        "user_id": user.id,
        "calendar_url": f"http://127.0.0.1:8000/calendar/{user.id}"
    }