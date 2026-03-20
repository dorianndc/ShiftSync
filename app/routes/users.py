from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.schemas import UserCreate
from app.services.ics_service import generate_ics_for_user
from fastapi import BackgroundTasks
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import User
from app.schemas import UserCreate
from app.services.sync_service import run_user_sync

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/create-user")
def create_user(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(User.email == payload.email).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    user = User(
        email=payload.email,
        planning_login=payload.login,
        planning_password=payload.password,
        status="pending"
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    background_tasks.add_task(run_user_sync, user.id)

    return {
        "message": "User créé, synchronisation en cours",
        "user_id": user.id,
        "status": user.status,
        "calendar_url": f"http://127.0.0.1:8000/calendar/{user.id}"
    }

@router.get("/user/{user_id}")
def get_user_status(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    return {
        "user_id": user.id,
        "email": user.email,
        "status": user.status,
        "ics_path": user.ics_path
    }