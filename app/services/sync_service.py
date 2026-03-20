import traceback

from app.database import SessionLocal
from app.models import User
from app.services.ics_service import generate_ics_for_user


def run_user_sync(user_id: int):
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"[SYNC] Utilisateur {user_id} introuvable")
            return

        print(f"[SYNC] Début sync user {user_id}")
        user.status = "processing"
        db.commit()
        db.refresh(user)

        ics_path = generate_ics_for_user(user)

        user.ics_path = ics_path
        user.status = "ready"
        db.commit()

        print(f"[SYNC] Sync OK user {user_id} -> {ics_path}")

    except Exception as e:
        print(f"[SYNC] Erreur pour user {user_id}: {e}")
        traceback.print_exc()

        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.status = "error"
            db.commit()

    finally:
        db.close()