from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import delete, func, select

from backend.api.common import lookup
from backend.auth import audit, require
from backend.biometrics import cipher, decode_image
from backend.db import get_db
from backend.models import (
    AttendanceRecord,
    Consent,
    Enrollment,
    FaceTemplate,
    Leave,
    Person,
    PersonDetails,
    ProfilePhoto,
    SessionMember,
)
from backend.people import (
    bump_index,
    clear_biometrics,
    person_dict,
    revoke_biometrics,
    save_person,
    type_condition,
)
from backend.schemas import ConsentInput, PersonInput, ReasonInput

router = APIRouter()


@router.get("/people")
def people(
    q: str = "",
    category: str | None = None,
    person_type: str | None = None,
    department_id: int | None = None,
    class_id: int | None = None,
    section: str | None = None,
    active: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort: Literal["name", "id"] = "name",
    user=Depends(require("read")),
    db=Depends(get_db),
):
    query = select(Person).join(PersonDetails)
    if person_type:
        query = query.where(type_condition(person_type))
    if q:
        query = query.where(
            Person.full_name.icontains(q, autoescape=True)
            | Person.institutional_id.icontains(q, autoescape=True)
        )
    for column, value in [
        (Person.category, category),
        (Person.department_id, department_id),
        (PersonDetails.class_id, class_id),
        (PersonDetails.section, section),
        (Person.active, active),
    ]:
        if value is not None:
            query = query.where(column == value)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(Person.full_name if sort == "name" else Person.institutional_id)
    return {
        "total": total,
        "items": [person_dict(db, p) for p in db.scalars(query.offset(offset).limit(limit))],
    }


@router.post("/people", status_code=201)
def add_person(data: PersonInput, user=Depends(require("people")), db=Depends(get_db)):
    return person_dict(db, save_person(db, user, data))


@router.get("/people/types")
def person_types(user=Depends(require("read")), db=Depends(get_db)):
    custom = db.scalars(
        select(Person.custom_type)
        .where(Person.custom_type.is_not(None))
        .distinct()
        .order_by(Person.custom_type)
    ).all()
    return ["Student", "Teacher", "Staff", "Other", *custom]


@router.get("/people/{person_id}")
def person(person_id: int, user=Depends(require("read")), db=Depends(get_db)):
    return person_dict(db, lookup(db, Person, person_id))


@router.put("/people/{person_id}")
def update_person(
    person_id: int, data: PersonInput, user=Depends(require("people")), db=Depends(get_db)
):
    return person_dict(db, save_person(db, user, data, lookup(db, Person, person_id)))


@router.post("/people/{person_id}/consent", status_code=201)
def consent(
    person_id: int, data: ConsentInput, user=Depends(require("enroll")), db=Depends(get_db)
):
    person = lookup(db, Person, person_id)
    if person.is_minor and not data.guardian:
        raise HTTPException(422, "Guardian authorization is required for minors")
    entry = Consent(person_id=person_id, recorded_by=user.id, **data.model_dump())
    db.add(entry)
    db.flush()
    audit(db, user, "consent_recorded", "person", person_id, after={"consent_id": entry.id})
    db.commit()
    return {"id": entry.id}


@router.get("/people/{person_id}/enrollments")
def enrollment_history(person_id: int, user=Depends(require("enroll")), db=Depends(get_db)):
    lookup(db, Person, person_id)
    return {
        "consents": [
            {
                "id": c.id,
                "basis": c.basis,
                "statement": c.statement,
                "guardian": c.guardian,
                "created_at": c.created_at,
                "revoked_at": c.revoked_at,
            }
            for c in db.scalars(select(Consent).where(Consent.person_id == person_id))
        ],
        "enrollments": [
            {"id": e.id, "samples": e.sample_count, "created_at": e.created_at}
            for e in db.scalars(select(Enrollment).where(Enrollment.person_id == person_id))
        ],
    }


@router.post("/people/{person_id}/enroll")
def enroll(
    person_id: int,
    consent_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    user=Depends(require("enroll")),
    db=Depends(get_db),
):
    if not 3 <= len(files) <= 12:
        raise HTTPException(422, "Provide 3–12 distinct images")
    images = [f.file.read(request.app.state.settings.max_upload_bytes + 1) for f in files]
    if any(len(image) > request.app.state.settings.max_upload_bytes for image in images):
        raise HTTPException(413, "An enrollment image is too large")
    return request.app.state.vision.enroll(db, user, person_id, consent_id, images)


@router.delete("/people/{person_id}/biometrics", status_code=204)
def revoke(person_id: int, data: ReasonInput, user=Depends(require("enroll")), db=Depends(get_db)):
    revoke_biometrics(db, user, person_id, data.reason)


@router.post("/people/{person_id}/photo", status_code=204)
def upload_photo(
    person_id: int,
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require("people")),
    db=Depends(get_db),
):
    import cv2

    lookup(db, Person, person_id)
    image = decode_image(file.file.read(request.app.state.settings.max_upload_bytes + 1))
    h, w = image.shape[:2]
    image = cv2.resize(image, (max(1, int(w * min(1, 400 / w))), max(1, int(h * min(1, 400 / w)))))
    _, content = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    photo = db.get(ProfilePhoto, person_id) or ProfilePhoto(person_id=person_id)
    photo.encrypted_jpeg = cipher(request.app.state.settings).encrypt(content.tobytes())
    db.add(photo)
    audit(db, user, "profile_photo_updated", "person", person_id)
    db.commit()


@router.get("/people/{person_id}/photo")
def get_photo(
    person_id: int, request: Request, user=Depends(require("people")), db=Depends(get_db)
):
    photo = lookup(db, ProfilePhoto, person_id)
    audit(db, user, "profile_photo_viewed", "person", person_id)
    db.commit()
    return Response(
        cipher(request.app.state.settings).decrypt(photo.encrypted_jpeg), media_type="image/jpeg"
    )


@router.delete("/people/{person_id}", status_code=204)
def delete_person(
    person_id: int, data: ReasonInput, user=Depends(require("privacy")), db=Depends(get_db)
):
    person = lookup(db, Person, person_id)
    retained = (
        db.scalar(
            select(SessionMember.person_id).where(SessionMember.person_id == person_id).limit(1)
        )
        or db.scalar(select(Leave.id).where(Leave.person_id == person_id).limit(1))
        or db.scalar(
            select(AttendanceRecord.id).where(AttendanceRecord.person_id == person_id).limit(1)
        )
    )
    if retained:
        before = person_dict(db, person)
        person.active = False
        clear_biometrics(db, person_id)
        audit(
            db,
            user,
            "person_removed",
            "person",
            person_id,
            before=before,
            after={"active": False, "history_retained": True},
            reason=data.reason,
        )
        db.commit()
        return
    # Delete dependents in foreign-key order while retaining administrative audit history.
    for model in (FaceTemplate, Enrollment, Consent, ProfilePhoto, PersonDetails):
        db.execute(delete(model).where(model.person_id == person_id))
    db.delete(person)
    bump_index(db)
    audit(db, user, "person_deleted", "person", person_id, reason=data.reason)
    db.commit()
