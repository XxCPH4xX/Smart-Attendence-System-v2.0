from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from backend.db import utcnow
from backend.models import Person
from backend.people import save_person
from backend.schemas import PersonInput

DEMO_ID = "DEMO-001"
DEMO_NOTE = "Demo profile for an authorized face-recognition test. Not a real student record."


def ensure_demo_person(db, user, timezone):
    person = db.scalar(select(Person).where(Person.institutional_id == DEMO_ID))
    if person:
        if person.notes != DEMO_NOTE or person.category != "student":
            raise HTTPException(409, "DEMO-001 is already in use. Choose that person in People.")
        if not person.active:
            raise HTTPException(409, "The demo profile is inactive. Reactivate it in People first.")
        return person
    return save_person(
        db,
        user,
        PersonInput(
            institutional_id=DEMO_ID,
            full_name="Demo Student",
            category="student",
            joined_on=utcnow().astimezone(ZoneInfo(timezone)).date(),
            notes=DEMO_NOTE,
        ),
    )
