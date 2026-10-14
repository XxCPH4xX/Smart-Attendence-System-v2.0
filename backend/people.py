from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from backend.auth import audit
from backend.db import utcnow
from backend.models import (
    Catalog,
    Consent,
    Enrollment,
    FaceTemplate,
    Person,
    PersonDetails,
    Policy,
    ProfilePhoto,
)
from backend.schemas import PolicyInput


def get_policy(db):
    policy = db.get(Policy, 1)
    return PolicyInput(**(policy.values if policy else {}))


def institution_context(db, settings):
    policy = get_policy(db)
    return {
        "institution": policy.institution_name or settings.institution,
        "timezone": policy.institution_timezone or settings.timezone,
    }


def bump_index(db):
    db.execute(update(Policy).where(Policy.id == 1).values(index_version=Policy.index_version + 1))


def validate_catalog(db, identifier, kind):
    if identifier is None:
        return
    value = db.get(Catalog, identifier)
    if not value or value.kind != kind:
        raise HTTPException(422, f"Invalid {kind} selection")


def person_dict(db, person):
    details = db.get(PersonDetails, person.id)
    return {
        "id": person.id,
        "institutional_id": person.institutional_id,
        "full_name": person.full_name,
        "category": person.category,
        "custom_type": person.custom_type,
        "person_type": person.custom_type or person.category.title(),
        "age": person.age,
        "email": person.email,
        "phone": person.phone,
        "department_id": person.department_id,
        "active": person.active,
        "joined_on": person.joined_on.isoformat(),
        "notes": person.notes,
        "is_minor": person.is_minor,
        "details": {
            c.name: getattr(details, c.name)
            for c in PersonDetails.__table__.columns
            if c.name != "person_id"
        }
        if details
        else {},
        "enrolled": bool(
            db.scalar(
                select(FaceTemplate.id)
                .join(Enrollment, Enrollment.id == FaceTemplate.enrollment_id)
                .join(Consent, Consent.id == Enrollment.consent_id)
                .where(
                    FaceTemplate.person_id == person.id,
                    FaceTemplate.expires_at > utcnow(),
                    Consent.revoked_at.is_(None),
                    Consent.guardian.is_not(None) if person.is_minor else True,
                )
                .limit(1)
            )
        ),
    }


def save_person(db, user, data, person=None, *, commit=True):
    validate_catalog(db, data.department_id, "department")
    validate_catalog(db, data.details.class_id, "class")
    validate_catalog(db, data.details.shift_id, "shift")
    for course_id in data.details.assigned_courses:
        validate_catalog(db, course_id, "course")
    before = person_dict(db, person) if person else None
    if person and person.category != data.category:
        raise HTTPException(
            409, "Category is immutable; archive and register a new category record"
        )
    fields = data.model_dump(exclude={"details"}, mode="python")
    if data.custom_type:
        existing_type = db.scalar(
            select(Person.custom_type)
            .where(func.lower(Person.custom_type) == data.custom_type.lower())
            .limit(1)
        )
        fields["custom_type"] = existing_type or data.custom_type
    if not person:
        person = Person(**fields)
        db.add(person)
        db.flush()
        db.add(PersonDetails(person_id=person.id, **data.details.model_dump()))
    else:
        for key, value in fields.items():
            setattr(person, key, value)
        details = db.get(PersonDetails, person.id)
        for key, value in data.details.model_dump().items():
            setattr(details, key, value)
    db.flush()
    bump_index(db)
    audit(
        db,
        user,
        "person_updated" if before else "person_created",
        "person",
        person.id,
        before=before,
        after=person_dict(db, person),
    )
    if commit:
        db.commit()
    return person


def type_condition(label):
    category = label.lower()
    if category in {"student", "teacher", "staff", "other"}:
        return (Person.category == category) & Person.custom_type.is_(None)
    return func.lower(Person.custom_type) == category


def clear_biometrics(db, person_id):
    """Remove biometric data and revoke consent within the caller's transaction."""
    db.execute(delete(FaceTemplate).where(FaceTemplate.person_id == person_id))
    db.execute(delete(ProfilePhoto).where(ProfilePhoto.person_id == person_id))
    for consent in db.scalars(
        select(Consent).where(Consent.person_id == person_id, Consent.revoked_at.is_(None))
    ):
        consent.revoked_at = utcnow()
    bump_index(db)


def revoke_biometrics(db, user, person_id, reason):
    if not db.get(Person, person_id):
        raise HTTPException(404, "Person not found")
    clear_biometrics(db, person_id)
    audit(db, user, "biometrics_revoked", "person", person_id, reason=reason)
    db.commit()
