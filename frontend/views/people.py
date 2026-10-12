import hashlib
from datetime import date

import streamlit as st

from frontend.client import can, person_label, request


def person_form(person=None):
    person = person or {}
    details = person.get("details", {})
    catalog = request("GET", "/catalog")
    categories = ["student", "teacher", "staff", "other"]
    category = st.selectbox(
        "Person category",
        categories,
        index=categories.index(person.get("category", "student")),
        disabled=bool(person),
    )

    def catalog_select(label, kind, selected):
        options = {None: "Unassigned", **{c["id"]: c["name"] for c in catalog if c["kind"] == kind}}
        return st.selectbox(
            label,
            list(options),
            format_func=options.get,
            index=list(options).index(selected) if selected in options else 0,
        )

    with st.form("person_form"):
        a, b = st.columns(2)
        with a:
            name = st.text_input("Full name", person.get("full_name", ""), max_chars=160)
            institutional_id = st.text_input(
                "Institutional ID", person.get("institutional_id", ""), max_chars=80
            )
            email = st.text_input("Email (optional)", person.get("email") or "")
            phone = st.text_input("Phone (optional)", person.get("phone") or "")
            department = catalog_select("Department", "department", person.get("department_id"))
            joined = st.date_input(
                "Joining / enrollment date",
                date.fromisoformat(person["joined_on"]) if person else date.today(),
            )
        with b:
            specific = {}
            if category == "student":
                specific["student_id"] = (
                    st.text_input("Student ID", details.get("student_id") or "") or None
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
                    st.text_input("Employee ID", details.get("employee_id") or "") or None
                )
                specific["designation"] = (
                    st.text_input("Designation / job title", details.get("designation") or "")
                    or None
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
            active = st.checkbox("Active", person.get("active", True))
            minor = st.checkbox(
                "Minor — guardian authorization required for enrollment",
                person.get("is_minor", False),
            )
            notes = st.text_area("Notes (optional)", person.get("notes", ""), max_chars=3000)
        submitted = st.form_submit_button("Save person", type="primary")
    if submitted:
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
        st.success(f"Saved {saved['full_name']}. Attendance records are preserved.")
        return saved
    return None


def enrollment(person):
    st.subheader("Face enrollment")
    st.info(
        "Enrollment stores encrypted facial templates for attendance matching. Camera footage and enrollment images are not retained. Participation can be revoked; manual attendance is available. Recognition is fallible and staff must verify camera attendance."
    )
    history = request("GET", f"/people/{person['id']}/enrollments")
    with st.expander("Enrollment authorization", expanded=not history["consents"]):
        with st.form("consent"):
            basis = st.selectbox(
                "Authorization basis", ["explicit_consent", "institutional_authorization"]
            )
            guardian = st.text_input(
                "Guardian name / authorization reference"
                + (" (required)" if person["is_minor"] else " (if applicable)")
            )
            statement = st.text_area(
                "Authorization record",
                placeholder="Record what was explained, the agreed purpose, and the consent or institutional authorization reference.",
            )
            acknowledged = st.checkbox(
                "I have explained the collection, retention period, revocation process, and manual alternative."
            )
            if st.form_submit_button("Record authorization", disabled=not acknowledged):
                request(
                    "POST",
                    f"/people/{person['id']}/consent",
                    json={"basis": basis, "statement": statement, "guardian": guardian or None},
                )
                st.rerun()
    consents = {c["id"]: c for c in history["consents"] if not c["revoked_at"]}
    if not consents:
        st.caption("Record authorization before capturing face samples.")
        return
    consent_id = st.selectbox(
        "Current authorization",
        list(consents),
        format_func=lambda i: f"#{i} · {consents[i]['basis']}",
    )
    st.caption(
        "Capture 3–12 distinct samples with small changes in head angle and lighting. Remove other people from the frame."
    )
    source = st.radio("Samples", ["Upload images", "Webcam capture"], horizontal=True)
    capture_key = f"samples_{person['id']}"
    st.session_state.setdefault(capture_key, [])
    if source == "Upload images":
        files = st.file_uploader(
            "Face samples", type=["jpg", "jpeg", "png"], accept_multiple_files=True
        )
        images = [(f.name, f.getvalue()) for f in files]
    else:
        capture = st.camera_input("Capture one sample at a time")
        if capture and st.button("Check and keep this sample"):
            content = capture.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            if digest in [hashlib.sha256(v).hexdigest() for _, v in st.session_state[capture_key]]:
                st.warning("This sample is already captured.")
            elif len(st.session_state[capture_key]) >= 12:
                st.warning("Twelve samples are already captured.")
            else:
                result = request(
                    "POST",
                    "/vision/quality",
                    files={"file": ("capture.jpg", content, "image/jpeg")},
                )
                if result["acceptable"]:
                    st.session_state[capture_key].append(
                        (f"sample-{len(st.session_state[capture_key]) + 1}.jpg", content)
                    )
                    st.success("Sample accepted")
                else:
                    st.warning("; ".join(result["feedback"]) or "No face detected")
        images = st.session_state[capture_key]
        st.write(f"{len(images)} samples captured")
        if st.button("Clear captured samples"):
            st.session_state[capture_key] = []
            st.rerun()
    if images and st.button("Check first image quality"):
        result = request("POST", "/vision/quality", files={"file": (images[0][0], images[0][1])})
        st.write(result)
    if st.button("Validate and enroll face", type="primary", disabled=not 3 <= len(images) <= 12):
        with st.spinner("Checking samples, extracting templates, and updating recognition…"):
            result = request(
                "POST",
                f"/people/{person['id']}/enroll",
                params={"consent_id": consent_id},
                files=[("files", (name, content)) for name, content in images],
            )
        st.session_state[capture_key] = []
        st.success(f"Enrolled {result['samples']} samples. Recognition index updated.")
    with st.expander("Enrollment history"):
        st.dataframe(history["enrollments"], use_container_width=True, hide_index=True)
    with st.expander("Revoke authorization and delete biometric data"):
        reason = st.text_input("Reason for revocation")
        confirmed = st.checkbox("Delete all templates and the profile photo for this person")
        if st.button("Revoke biometrics", disabled=not confirmed):
            request("DELETE", f"/people/{person['id']}/biometrics", json={"reason": reason})
            st.session_state[capture_key] = []
            st.rerun()


def register():
    st.caption(
        "1 · Personal details     2 · Category information     3 · Authorized face capture     4 · Validation"
    )
    saved = person_form()
    if saved:
        st.session_state.registered_person = saved
    if st.session_state.get("registered_person") and can("enroll"):
        enrollment(st.session_state.registered_person)


def manage():
    a, b, c, d = st.columns(4)
    q = a.text_input("Search name or ID")
    category = b.selectbox("Category", ["All", "student", "teacher", "staff", "other"])
    state = c.selectbox("Account status", ["All", "Active", "Inactive"])
    sort = d.selectbox("Sort by", ["name", "id"])
    catalog = request("GET", "/catalog")
    departments = {
        0: "All departments",
        **{x["id"]: x["name"] for x in catalog if x["kind"] == "department"},
    }
    classes = {0: "All classes", **{x["id"]: x["name"] for x in catalog if x["kind"] == "class"}}
    a, b, c = st.columns(3)
    department = a.selectbox("Department", list(departments), format_func=departments.get)
    class_id = b.selectbox("Class", list(classes), format_func=classes.get)
    section = c.text_input("Section filter")
    page = st.number_input("Page", min_value=1, value=1, step=1)
    params = dict(q=q, sort=sort, offset=(page - 1) * 25, limit=25)
    if category != "All":
        params["category"] = category
    if state != "All":
        params["active"] = state == "Active"
    if department:
        params["department_id"] = department
    if class_id:
        params["class_id"] = class_id
    if section:
        params["section"] = section
    response = request("GET", "/people", params=params)
    st.caption(f"{response['total']} people")
    items = response["items"]
    st.dataframe(
        [
            {
                k: p[k]
                for k in ["id", "institutional_id", "full_name", "category", "active", "enrolled"]
            }
            for p in items
        ],
        hide_index=True,
        use_container_width=True,
    )
    if not items:
        return
    options = {p["id"]: p for p in items}
    selected = st.selectbox(
        "Open person", list(options), format_func=lambda i: person_label(options[i])
    )
    person = options[selected]
    if can("people"):
        with st.expander("Edit profile"):
            person_form(person)
        with st.expander("Profile photo"):
            if st.button("View stored profile photo"):
                st.image(request("GET", f"/people/{selected}/photo"), width=240)
            photo = st.file_uploader("Update photo", type=["jpg", "jpeg", "png"])
            if photo and st.button("Save profile photo"):
                request(
                    "POST",
                    f"/people/{selected}/photo",
                    files={"file": (photo.name, photo.getvalue())},
                )
                st.success("Photo saved securely")
    if can("enroll"):
        with st.container(border=True):
            enrollment(person)
    if can("privacy"):
        with st.expander("Delete person after retention"):
            reason = st.text_input("Deletion reason")
            confirmation = st.text_input("Type the institutional ID to confirm deletion")
            if st.button("Delete person", disabled=confirmation != person["institutional_id"]):
                request("DELETE", f"/people/{selected}", json={"reason": reason})
                st.rerun()
