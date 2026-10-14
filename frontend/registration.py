import json
from datetime import date
from zoneinfo import ZoneInfo

import streamlit as st
from pydantic import ValidationError

from backend.db import utcnow
from backend.schemas import PersonInput
from frontend.client import request, validation_message
from frontend.design import empty, heading
from frontend.face_photos import clear_photos, photo_editor
from frontend.navigation import PAGE_CATEGORIES, open_page, option_buttons

DRAFT_PHOTOS = "registration_draft"
STEPS = ["Category", "Personal details", "Institution", "Face enrollment", "Review"]


def begin_registration(category=None):
    for key in list(st.session_state):
        if str(key).startswith("registration:"):
            del st.session_state[key]
    clear_photos(DRAFT_PHOTOS)
    st.session_state.registration_draft = {
        "category": category,
        "step": 2 if category else 1,
        "person": {},
        "details": {},
    }
    open_page("Enrollment", "New registration")


def validate_person(values):
    try:
        return PersonInput(**values).model_dump(mode="json")
    except ValidationError as error:
        for issue in error.errors(include_input=False):
            st.error(validation_message({**issue, "loc": ("body", *issue["loc"])}))
        return None


def catalog_picker(label, kind, entries, value=None, key=None):
    choices = {
        None: "Not assigned",
        **{item["id"]: item["name"] for item in entries if item["kind"] == kind},
    }
    return st.selectbox(
        label,
        list(choices),
        index=list(choices).index(value) if value in choices else 0,
        format_func=choices.get,
        key=key,
    )


def select_category(category):
    draft = st.session_state.registration_draft
    if draft["category"] != category:
        draft["details"] = {}
        draft["person"].pop("details", None)
        draft["person"].pop("custom_type", None)
    draft.update(category=category, step=2)


def advance(step):
    st.session_state.registration_draft["step"] = step


def save_personal():
    draft = st.session_state.registration_draft
    fields = st.session_state
    age = fields["registration:age"]
    if age is None:
        st.session_state.registration_error = "Enter an age to continue."
        return
    values = validate_person(
        {
            **draft["person"],
            "full_name": fields["registration:name"],
            "institutional_id": fields["registration:identifier"],
            "age": age,
            "phone": fields["registration:phone"] or None,
            "email": fields["registration:email"] or None,
            "category": draft["category"],
            "custom_type": fields.get("registration:custom") or None
            if draft["category"] == "other"
            else None,
            "joined_on": draft["person"].get("joined_on", fields["registration:today"]),
        }
    )
    if values:
        draft.update(person=values, step=3)


def save_institution():
    draft = st.session_state.registration_draft
    fields = st.session_state
    names = (
        ["class_id", "section", "academic_year", "semester", "roll_number"]
        if draft["category"] == "student"
        else ["designation", "shift_id"]
    )
    if draft["category"] == "teacher":
        names.append("assigned_courses")
    details = {
        name: fields.get("registration:" + name) or ([] if name == "assigned_courses" else None)
        for name in names
    }
    values = validate_person(
        {
            **draft["person"],
            "department_id": fields["registration:department"],
            "joined_on": fields["registration:joined"].isoformat(),
            "details": details,
        }
    )
    if values:
        draft.update(person=values, details=details, step=4)


def finish_registration():
    from frontend.client import APIError

    draft = st.session_state.registration_draft
    manual = draft.get("manual_attendance", False)
    photos = [] if manual else st.session_state.get(f"samples_{DRAFT_PHOTOS}", [])
    payload = {
        "person": draft["person"],
        "manual_attendance": manual,
        "consent": None if manual else draft["consent"],
    }
    try:
        result = request(
            "POST",
            "/registrations",
            data={"payload": json.dumps(payload)},
            files=[("files", (name, content)) for name, content in photos],
        )
    except APIError as error:
        st.session_state.registration_error = str(error)
        return
    category = draft["category"]
    clear_photos(DRAFT_PHOTOS)
    st.session_state.pop("registration_draft", None)
    st.session_state.notice = "Registration complete. " + result["full_name"] + " is ready."
    open_page(
        PAGE_CATEGORIES.get(category, "Enrollment"),
        "Directory" if category in PAGE_CATEGORIES else "Other people",
        person_id=result["id"],
    )


def wizard():
    draft = st.session_state.setdefault(
        "registration_draft", {"category": None, "step": 1, "person": {}, "details": {}}
    )
    step = draft["step"]
    error = st.session_state.pop("registration_error", None)
    if error:
        st.error(error)
    for index, column in enumerate(st.columns(5), 1):
        with column:
            st.html(
                f'<div class="sa-step {"active" if index == step else ""}"><span>{"✓" if index < step else index}</span>{STEPS[index - 1]}</div>'
            )
    if step > 1:
        st.button(
            "Back",
            icon=":material/arrow_back:",
            key="registration_back",
            on_click=advance,
            args=(step - 1,),
        )
    if step == 1:
        heading(
            "Who are you registering?",
            "Choose a category to tailor the registration form.",
            "Enrollment / New registration",
        )
        for column, category, icon, description in zip(
            st.columns(4),
            ["student", "teacher", "staff", "other"],
            ["school", "cast_for_education", "badge", "person_add"],
            [
                "Classes, sections and academic details",
                "Departments and teaching schedules",
                "Departments, roles and shifts",
                "Visitors, contractors and custom roles",
            ],
            strict=True,
        ):
            with column, st.container(border=True):
                st.subheader(category.title())
                st.caption(description)
                st.button(
                    "Register " + category,
                    icon=f":material/{icon}:",
                    use_container_width=True,
                    on_click=select_category,
                    args=(category,),
                )
        return
    category = draft["category"]
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    if step == 2:
        heading(
            "Start with the essentials",
            "A name, unique ID and age identify the person.",
            f"Enrollment / {category.title()}",
        )
        person = draft["person"]
        with st.form("registration_personal"):
            left, right = st.columns(2)
            left.text_input(
                "Full name", person.get("full_name", ""), max_chars=160, key="registration:name"
            )
            right.text_input(
                "Institutional ID",
                person.get("institutional_id", ""),
                max_chars=80,
                key="registration:identifier",
            )
            left.number_input(
                "Age (years)",
                min_value=0,
                max_value=120,
                value=person.get("age"),
                step=1,
                key="registration:age",
            )
            right.text_input(
                "Phone (optional)", person.get("phone") or "", key="registration:phone"
            )
            left.text_input("Email (optional)", person.get("email") or "", key="registration:email")
            (
                right.text_input(
                    "Custom person type",
                    person.get("custom_type") or "",
                    placeholder="Contractor, Visitor…",
                    key="registration:custom",
                )
                if category == "other"
                else None
            )
            st.session_state["registration:today"] = today.isoformat()
            st.form_submit_button(
                "Continue to institutional details", type="primary", on_click=save_personal
            )
    elif step == 3:
        heading(
            "Institutional information",
            "Assign the person to the right class, department or shift.",
            f"Enrollment / {category.title()}",
        )
        catalog = request("GET", "/catalog")
        details = draft["details"]
        with st.form("registration_institution"):
            left, right = st.columns(2)
            with left:
                catalog_picker(
                    "Department / program",
                    "department",
                    catalog,
                    draft["person"].get("department_id"),
                    key="registration:department",
                )
                st.date_input(
                    "Joining date",
                    date.fromisoformat(draft["person"]["joined_on"]),
                    key="registration:joined",
                )
            with right:
                if category == "student":
                    details["class_id"] = catalog_picker(
                        "Class",
                        "class",
                        catalog,
                        details.get("class_id"),
                        key="registration:class_id",
                    )
                    details["section"] = (
                        st.text_input(
                            "Section", details.get("section") or "", key="registration:section"
                        )
                        or None
                    )
                else:
                    details["designation"] = (
                        st.text_input(
                            "Designation" if category == "teacher" else "Job title",
                            details.get("designation") or "",
                            key="registration:designation",
                        )
                        or None
                    )
                    details["shift_id"] = catalog_picker(
                        "Assigned shift",
                        "shift",
                        catalog,
                        details.get("shift_id"),
                        key="registration:shift_id",
                    )
            if category == "student":
                a, b, c = st.columns(3)
                details["academic_year"] = (
                    a.text_input(
                        "Academic session",
                        details.get("academic_year") or "",
                        key="registration:academic_year",
                    )
                    or None
                )
                details["semester"] = (
                    b.text_input(
                        "Semester", details.get("semester") or "", key="registration:semester"
                    )
                    or None
                )
                details["roll_number"] = (
                    c.text_input(
                        "Roll number",
                        details.get("roll_number") or "",
                        key="registration:roll_number",
                    )
                    or None
                )
            elif category == "teacher":
                courses = {
                    entry["id"]: entry["name"] for entry in catalog if entry["kind"] == "course"
                }
                details["assigned_courses"] = st.multiselect(
                    "Assigned courses",
                    list(courses),
                    default=details.get("assigned_courses", []),
                    key="registration:assigned_courses",
                    format_func=courses.get,
                )
            st.form_submit_button(
                "Continue to face enrollment", type="primary", on_click=save_institution
            )
    elif step == 4:
        heading(
            "Set up attendance",
            "Choose face recognition or the manual attendance alternative.",
            "Enrollment / Face enrollment",
        )
        method = option_buttons(
            "", ["Face recognition", "Manual attendance"], "registration:method"
        )
        draft["manual_attendance"] = method == "Manual attendance"
        if draft["manual_attendance"]:
            empty(
                "Ready for manual attendance",
                "The profile will be saved without face data. An authorized operator can record attendance.",
            )
            ready = True
        else:
            photo, permission = st.columns([1.3, 1])
            with permission, st.container(border=True):
                st.subheader("Permission & privacy")
                st.caption(
                    f"Encrypted face templates are kept for up to {config['policy']['template_retention_days']} days. Enrollment photos are processed in memory. Manual attendance remains available."
                )
                basis = st.selectbox(
                    "Authorization",
                    ["Personal consent", "Institutional authorization"],
                    key="registration:basis",
                )
                guardian = (
                    st.text_input("Guardian authorization reference", key="registration:guardian")
                    if draft["person"]["is_minor"]
                    else None
                )
                note = st.text_area(
                    "Authorization note",
                    value="Authorized face matching for attendance, with encrypted template storage and the option to revoke or use manual attendance.",
                    key="registration:note",
                )
                acknowledged = st.checkbox(
                    "I have the person's informed permission.", key="registration:acknowledged"
                )
                draft["consent"] = {
                    "basis": "explicit_consent"
                    if basis == "Personal consent"
                    else "institutional_authorization",
                    "statement": note,
                    "guardian": guardian or None,
                }
            with photo:
                photos = photo_editor(DRAFT_PHOTOS)
            ready = (
                acknowledged
                and len(note.strip()) >= 20
                and (not draft["person"]["is_minor"] or bool(guardian and guardian.strip()))
                and 3 <= len(photos) <= 12
            )
        st.button(
            "Review registration", type="primary", disabled=not ready, on_click=advance, args=(5,)
        )
    else:
        heading(
            "Review & register", "Nothing is saved until you confirm below.", "Enrollment / Review"
        )
        person = draft["person"]
        left, right = st.columns(2)
        with left, st.container(border=True):
            st.subheader(person["full_name"])
            st.write(person["institutional_id"])
            st.caption(
                f"{person.get('custom_type') or category.title()} · Age {person['age']} · Joined {person['joined_on']}"
            )
            if person.get("email"):
                st.write(person["email"])
            catalog = {entry["id"]: entry["name"] for entry in request("GET", "/catalog")}
            st.write("Department: " + catalog.get(person["department_id"], "Not assigned"))
            for field, value in draft["details"].items():
                if value:
                    label = field.replace("_", " ").title()
                    display = catalog.get(value, value) if isinstance(value, int) else value
                    if isinstance(value, list):
                        display = ", ".join(catalog.get(item, str(item)) for item in value)
                    st.write(f"{label}: {display}")
        manual = draft.get("manual_attendance", False)
        photos = [] if manual else st.session_state.get(f"samples_{DRAFT_PHOTOS}", [])
        with right, st.container(border=True):
            st.subheader("Attendance method")
            st.write("Manual attendance" if manual else "Face recognition")
            if photos:
                st.image([content for _, content in photos], width=100)
                st.caption(f"{len(photos)} photos · Permission recorded")
        st.button(
            "Confirm registration",
            type="primary",
            icon=":material/check:",
            on_click=finish_registration,
        )
    st.button("Discard draft", type="tertiary", on_click=begin_registration)
