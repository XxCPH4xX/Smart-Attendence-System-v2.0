from fastapi import APIRouter, Depends, Request

from backend.auth import require
from backend.db import get_db
from backend.demo import ensure_demo_person
from backend.people import institution_context, person_dict

router = APIRouter()


@router.post("/demo/person")
def prepare_demo(request: Request, user=Depends(require("people")), db=Depends(get_db)):
    person = ensure_demo_person(
        db, user, institution_context(db, request.app.state.settings)["timezone"]
    )
    return person_dict(db, person)
