from datetime import date
from zoneinfo import ZoneInfo

import streamlit as st

from backend.db import utcnow
from frontend.client import can, people_options, person_label, request
from frontend.controls import (
    control_key,
    delete_person_button,
    people_table,
    reset_button,
    reset_section,
)
from frontend.face_photos import clear_photos, photo_editor
from frontend.navigation import navigate, option_buttons, redirect


def person_form(person=None):
    person = person or {}
    scope = f"person_form_{person.get('id', 'new')}"
    reset_button(scope, label="Reset form")
    details = person.get("details", {})
    catalog = request("GET", "/catalog")
    config = request("GET", "/settings")
    categories = ["student", "teacher", "staff", "other"]
    category = st.selectbox(
        "Person type",
        categories,
        format_func=str.title,
        index=categories.index(person.get("category", "student")),
        disabled=bool(person),
        key=control_key(scope, "category"),
    )

    def catalog_select(label, kind, selected):
        options = {None: "Not set", **{c["id"]: c["name"] for c in catalog if c["kind"] == kind}}
        return st.selectbox(
            label,
            list(options),
            format_func=options.get,
            index=list(options).index(selected) if selected in options else 0,
        )

    with st.form(control_key(scope, "form")):
        a, b = st.columns(2)
        name = a.text_input("Full name", person.get("full_name", ""), max_chars=160)
        institutional_id = b.text_input(
            "Student or employee ID",
            person.get("institutional_id", ""),
            max_chars=80,
            help="A unique ID, such as STU-1001.",
        )
        minor = st.checkbox("This person is under 18", person.get("is_minor", False))
        with st.expander("Optional details"):
            a, b = st.columns(2)
            with a:
                email = st.text_input("Email", person.get("email") or "")
                phone = st.text_input("Phone", person.get("phone") or "")
                department = catalog_select("Department", "department", person.get("department_id"))
                joined = st.date_input(
                    "Joining date",
                    date.fromisoformat(person["joined_on"])
                    if person
                    else utcnow().astimezone(ZoneInfo(config["timezone"])).date(),
                )
                active = st.checkbox("Allow this person to check in", person.get("active", True))
                notes = st.text_area("Notes", person.get("notes", ""), max_chars=3000)
            with b:
                specific = {}
                if category == "student":
                    specific["student_id"] = (
                        st.text_input("Additional student ID", details.get("student_id") or "")
                        or None
                    )
                    specific["class_id"] = catalog_select(
                        "Class / program", "class", details.get("class_id")
                    )
                    for field, label in [
                        ("section", "Section"),
                        ("academic_year", "Academic year"),
                        ("semester", "Semester"),
                        ("roll_number", "Roll number"),
                    ]:
                        specific[field] = st.text_input(label, details.get(field) or "") or None
                else:
                    specific["employee_id"] = (
                        st.text_input("Additional employee ID", details.get("employee_id") or "")
                        or None
                    )
                    specific["designation"] = (
                        st.text_input("Job title", details.get("designation") or "") or None
                    )
                    specific["shift_id"] = catalog_select(
                        "Assigned shift", "shift", details.get("shift_id")
                    )
                    if category == "teacher":
                        courses = {c["id"]: c["name"] for c in catalog if c["kind"] == "course"}
                        specific["assigned_courses"] = st.multiselect(
                            "Assigned courses",
                            list(courses),
                            default=details.get("assigned_courses", []),
                            format_func=courses.get,
                        )
        submitted = st.form_submit_button(
            "Save changes" if person else "Save and add face", type="primary"
        )
    if submitted:
        if not name.strip() or not institutional_id.strip():
            st.error("Enter a full name and a unique ID to continue.")
            return None
        data = dict(
            institutional_id=institutional_id,
            full_name=name,
            category=category,
            email=email or None,
            phone=phone or None,
            department_id=department,
            active=active,
            joined_on=joined.isoformat(),
            is_minor=minor,
            notes=notes,
            details=specific,
        )
        saved = request(
            "PUT" if person else "POST",
            f"/people/{person['id']}" if person else "/people",
            json=data,
        )
        return saved
    return None


def enrollment(person):
    person_id = person["id"]
    scope = f"enrollment_{person_id}"
    reset_button(
        scope,
        label="Reset enrollment form",
        clear_keys=(
            f"samples_{person_id}",
            f"replace_face_{person_id}",
            f"photo_source_{person_id}",
            f"retake_{person_id}",
            f"photo_notice_{person_id}",
        ),
    )
    st.subheader(person_label(person))
    if not person["active"]:
        st.info("Restore this person from People → Removed people before adding face samples.")
        return
    history = request("GET", f"/people/{person_id}/enrollments")
    consents = [c for c in history["consents"] if not c["revoked_at"]]
    replacing = st.session_state.get(f"replace_face_{person_id}", False)
    if person["enrolled"] and not replacing:
        st.success("Face enrollment is complete. This person is ready for attendance.")
        if can("camera"):
            st.button(
                "Take attendance",
                type="primary",
                on_click=navigate,
                args=("Take attendance", person_id),
            )
        if st.button("Replace face samples"):
            st.session_state[f"replace_face_{person_id}"] = True
            st.rerun()
    elif not consents:
        days = request("GET", "/settings")["policy"]["template_retention_days"]
        st.markdown("#### 1. Permission to use facial recognition")
        st.write(
            f"We keep an encrypted face template for up to {days} days. Enrollment photos and camera footage are not saved. You can remove the template later or use manual attendance instead."
        )
        with st.form(control_key(scope, "consent")):
            basis = st.selectbox(
                "Permission type",
                ["explicit_consent", "institutional_authorization"],
                format_func=lambda x: "Personal consent"
                if x == "explicit_consent"
                else "Institutional authorization",
            )
            guardian = (
                st.text_input("Guardian name and authorization reference")
                if person["is_minor"]
                else None
            )
            statement = st.text_area(
                "Consent or authorization note",
                value="Consent given for face matching to record attendance, with encrypted template storage and the option to revoke or use manual attendance.",
            )
            acknowledged = st.checkbox(
                "I have the person's informed permission to enroll their face."
            )
            submitted = st.form_submit_button("Agree and continue", type="primary")
        if submitted:
            if not acknowledged:
                st.error("Confirm permission before continuing.")
            elif person["is_minor"] and not guardian:
                st.error("Add the guardian's authorization before continuing.")
            else:
                request(
                    "POST",
                    f"/people/{person_id}/consent",
                    json={"basis": basis, "statement": statement, "guardian": guardian or None},
                )
                st.rerun()
    else:
        st.caption("✓ Permission recorded")
        st.markdown("#### 2. Add three clear face photos")
        st.write(
            "Take one looking straight ahead, one slightly left, and one slightly right. Keep only your face in the picture."
        )
        images = photo_editor(person_id)
        count = len(images)
        if st.button("Save face and finish", type="primary", disabled=not 3 <= count <= 12):
            with st.spinner("Checking your photos and saving the face template…"):
                request(
                    "POST",
                    f"/people/{person_id}/enroll",
                    params={"consent_id": consents[-1]["id"]},
                    files=[("files", (name, content)) for name, content in images],
                )
            clear_photos(person_id)
            st.session_state[f"replace_face_{person_id}"] = False
            st.session_state.notice = "Face saved. You can now try attendance with the camera."
            st.rerun()
    with st.expander("Enrollment history and removal"):
        st.dataframe(history["enrollments"], use_container_width=True, hide_index=True)
        if consents or person["enrolled"]:
            reason = st.text_input(
                "Reason for removing face data", key=control_key(scope, "reason")
            )
            confirmed = st.checkbox(
                "Remove the face template and profile photo, and revoke permission",
                key=control_key(scope, "confirm"),
            )
            if st.button("Remove face data", disabled=not confirmed):
                request("DELETE", f"/people/{person_id}/biometrics", json={"reason": reason})
                clear_photos(person_id)
                st.session_state.pop(f"replace_face_{person_id}", None)
                st.rerun()


def directory():
    scope = "directory"
    reset_button(scope, label="Reset filters")
    target = st.session_state.pop("directory_target", None)
    if target:
        reset_section(scope, ())
        person = request("GET", f"/people/{target}")
        st.session_state[control_key(scope, "search")] = person["institutional_id"]
        st.session_state[control_key(scope, "state")] = "Everyone"
        st.session_state[control_key(scope, "person")] = target
    a, b = st.columns([2, 1])
    q = a.text_input(
        "Find a person", placeholder="Search by name or ID", key=control_key(scope, "search")
    )
    category = b.selectbox(
        "Person type",
        ["All", "student", "teacher", "staff", "other"],
        format_func=str.title,
        key=control_key(scope, "category"),
    )
    params = dict(q=q, limit=25)
    if category != "All":
        params["category"] = category
    with st.expander("More filters"):
        catalog = request("GET", "/catalog")
        state = st.selectbox(
            "Show",
            ["Registered people", "Removed people", "Everyone"],
            key=control_key(scope, "state"),
        )
        department = st.selectbox(
            "Department",
            [None, *[c for c in catalog if c["kind"] == "department"]],
            format_func=lambda c: c["name"] if c else "All departments",
            key=control_key(scope, "department"),
        )
        class_entry = st.selectbox(
            "Class",
            [None, *[c for c in catalog if c["kind"] == "class"]],
            format_func=lambda c: c["name"] if c else "All classes",
            key=control_key(scope, "class"),
        )
        section = st.text_input("Section", key=control_key(scope, "section"))
        params["sort"] = st.selectbox(
            "Sort by",
            ["name", "id"],
            format_func=lambda x: "Name" if x == "name" else "ID",
            key=control_key(scope, "sort"),
        )
        if state != "Everyone":
            params["active"] = state == "Registered people"
        if department:
            params["department_id"] = department["id"]
        if class_entry:
            params["class_id"] = class_entry["id"]
        if section:
            params["section"] = section
    page = st.number_input("Page", min_value=1, value=1, step=1, key=control_key(scope, "page"))
    params["offset"] = (page - 1) * 25
    response = request("GET", "/people", params=params)
    st.caption(f"{response['total']} people found")
    items = response["items"]
    options = {p["id"]: p for p in items}
    selected = people_table(
        [
            {
                "Name": p["full_name"],
                "ID": p["institutional_id"],
                "Type": p["category"].title(),
                "Status": "Registered" if p["active"] else "Removed",
                "Face": "Ready" if p["enrolled"] else "Not added",
            }
            for p in items
        ],
        [p["id"] for p in items],
        options,
        scope,
    )
    if selected is None:
        return
    person = options[selected]
    if can("privacy") and person["active"]:
        delete_person_button(person, "People")
    if can("enroll") and person["active"]:
        st.button(
            "Manage this person's face",
            on_click=navigate,
            args=("People", selected, "Enroll a face"),
        )
    if can("people") and st.toggle(
        "Edit this person's details", key=control_key(scope, f"edit_{selected}")
    ):
        if person_form(person):
            st.session_state.notice = "Person updated."
            st.rerun()
    if can("people") and not person["active"]:
        st.info("This person has been removed. Their past records remain available.")
        if st.button("Restore person"):
            data = {key: value for key, value in person.items() if key not in {"id", "enrolled"}}
            request("PUT", f"/people/{selected}", json={**data, "active": True})
            st.session_state.notice = (
                "Person restored. Add their face again to use camera attendance."
            )
            st.rerun()
    if can("people"):
        with st.expander("Profile photo"):
            if st.button("View profile photo"):
                st.image(request("GET", f"/people/{selected}/photo"), width=240)
            photo = st.file_uploader(
                "Choose a profile photo",
                type=["jpg", "jpeg", "png"],
                key=control_key(scope, f"photo_{selected}"),
            )
            if photo and st.button("Save profile photo"):
                request(
                    "POST",
                    f"/people/{selected}/photo",
                    files={"file": (photo.name, photo.getvalue())},
                )
                st.success("Profile photo saved")


def render():
    actions = ["Find people"]
    if can("people"):
        actions.append("Add person")
    if can("enroll"):
        actions.append("Enroll a face")
    action = option_buttons("What would you like to do?", actions, key="people_action")
    if action == "Add person":
        st.caption("Start with a name and ID. You can fill in other details later.")
        saved = person_form()
        if saved:
            st.session_state.notice = (
                "Person saved. Next, add their face or return to the directory."
            )
            redirect("People", saved["id"], "Enroll a face" if can("enroll") else "Find people")
    elif action == "Enroll a face":
        options = people_options(active=True)
        if not options:
            st.info("Add a person first, then come back here to enroll their face.")
            st.button("Add a person", on_click=navigate, args=("People", None, "Add person"))
            return
        selected = st.session_state.get("selected_person")
        if selected not in options:
            st.session_state.selected_person = next(iter(options))
        person_id = st.selectbox(
            "Choose person",
            list(options),
            key="selected_person",
            format_func=lambda i: person_label(options[i]),
        )
        enrollment(options[person_id])
    else:
        directory()
