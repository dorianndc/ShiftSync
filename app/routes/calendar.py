from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter()


@router.get("/calendar/{user_id}")
def get_calendar(user_id: int):
    file_path = f"data/ics/user_{user_id}.ics"

    if not os.path.exists(file_path):
        return {"error": "Fichier non trouvé"}

    return FileResponse(file_path, media_type="text/calendar")