import os
from datetime import datetime, timedelta


def generate_ics_for_user(user):
    os.makedirs("data/ics", exist_ok=True)

    file_path = f"data/ics/user_{user.id}.ics"

    now = datetime.utcnow()
    start = now + timedelta(hours=1)
    end = start + timedelta(hours=2)

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:ShiftSync Test User {user.id}
DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}
END:VEVENT
END:VCALENDAR
"""

    with open(file_path, "w") as f:
        f.write(ics_content)

    return file_path