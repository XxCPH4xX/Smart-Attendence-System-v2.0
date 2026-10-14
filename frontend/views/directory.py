from datetime import date

import streamlit as st

from frontend.client import APIError, can, request
from frontend.controls import control_key, delete_selected_person, reset_button
from frontend.design import badge, confirmation, empty, person_identity
from frontend.navigation import PAGE_CATEGORIES, open_page, option_buttons
from frontend.registration import begin_registration, catalog_picker, validate_person


def profile_data(person):
    return {
        key: value for key, value in person.items() if key not in {"id", "enrolled", "person_type"}
    }


def change_status(person):
    request(
        "PUT",
        f"/people/{person['id']}",
        json={**profile_data(person), "active": not person["active"]},
    )
    st.session_state.notice = "Check-in access " + ("paused." if person["active"] else "restored.")


def open_profile(category, person_id, tab="Overview"):
    open_page(
        PAGE_CATEGORIES.get(category, "Enrollment"),
        "Directory" if category != "other" else "Other people",
        person_id=person_id,
    )
    st.session_state[f"profile_tab_{person_id}"] = tab


def directory(category):
    if st.session_state.get("profile_id"):
        profile(category, st.session_state.profile_id)
        return
    scope = f"directory_{category}"
    search, add = st.columns([3, 1])
    q = search.text_input(
        "Search " + category + " directory",
        placeholder="Search name or institutional ID",
        key=scope + "_search",
    )
    if can("people"):
        add.button(
            "Register " + category,
            icon=":material/person_add:",
            type="primary",
            use_container_width=True,
            on_click=begin_registration,
            args=(category,),
        )
    catalog = request("GET", "/catalog")
    params = {"category": category, "q": q, "limit": 20, "active": True}
    with st.expander("Filters & sorting", icon=":material/tune:"):
        a, b, c = st.columns(3)
        state = a.selectbox("Status", ["Active", "Paused / removed", "All"], key=scope + "_state")
        params.pop("active")
        if state != "All":
            params["active"] = state == "Active"
        sort = b.selectbox("Sort by", ["Name", "ID"], key=scope + "_sort")
        params["sort"] = "name" if sort == "Name" else "id"
        with c:
            department = catalog_picker(
                "Department", "department", catalog, key=scope + "_department"
            )
        if department:
            params["department_id"] = department
        if category == "student":
            a, b, c = st.columns(3)
            with a:
                classroom = catalog_picker("Class", "class", catalog, key=scope + "_class")
            section = b.text_input("Section", key=scope + "_section")
            academic = c.text_input("Academic session", key=scope + "_academic")
            semester = st.text_input("Semester", key=scope + "_semester")
            params.update(
                {
                    key: value
                    for key, value in {
                        "class_id": classroom,
                        "section": section,
                        "academic_year": academic,
                        "semester": semester,
                    }.items()
                    if value
                }
            )
        else:
            shift = catalog_picker("Shift", "shift", catalog, key=scope + "_shift")
            if shift:
                params["shift_id"] = shift
        if st.button("Clear filters", key=scope + "_clear"):
            for key in list(st.session_state):
                if str(key).startswith(scope):
                    del st.session_state[key]
            st.rerun()
    fingerprint = str(params)
    if st.session_state.get(scope + "_fingerprint") != fingerprint:
        st.session_state[scope + "_page"] = 1
        st.session_state[scope + "_fingerprint"] = fingerprint
    page = st.session_state.get(scope + "_page", 1)
    params["offset"] = (page - 1) * 20
    response = request("GET", "/people", params=params)
    if page > 1 and not response["items"]:
        st.session_state[scope + "_page"] = max(1, page - 1)
        st.rerun()
    st.caption(f"{response['total']} {category} profiles · Only {category} records are shown")
    if not response["items"]:
        empty(
            "No matching " + category + " profiles",
            "Adjust the search or filters, or register a new person.",
        )
        return
    names = {entry["id"]: entry["name"] for entry in catalog}
    for person in response["items"]:
        with st.container(border=True):
            identity, info, status, actions = st.columns([2.2, 1.7, 1.3, 1])
            with identity:
                person_identity(person)
            with info:
                details = person["details"]
                st.caption(names.get(person["department_id"], "No department"))
                st.write(
                    (
                        names.get(details.get("class_id"), "No class")
                        + (" · " + details["section"] if details.get("section") else "")
                    )
                    if category == "student"
                    else details.get("designation") or person["person_type"]
                )
            with status:
                badge(
                    "Face enrolled" if person["enrolled"] else "Face not added",
                    "good" if person["enrolled"] else "warn",
                )
                if not person["active"]:
                    st.caption("Check-in access paused")
            with (
                actions,
                st.popover("Actions", icon=":material/more_horiz:", use_container_width=True),
                st.container(key=f"person_actions_{person['id']}"),
            ):
                for label, tab, permission, icon in [
                    ("View profile", "Overview", "read", "person"),
                    ("Edit profile", "Personal info", "people", "edit"),
                    ("View attendance", "Attendance", "read", "event_available"),
                    ("Re-enroll face", "Face enrollment", "enroll", "face"),
                ]:
                    if can(permission):
                        st.button(
                            label,
                            key=f"{label}_{person['id']}",
                            icon=f":material/{icon}:",
                            type="tertiary",
                            on_click=open_profile,
                            args=(category, person["id"], tab),
                            use_container_width=True,
                        )
                if can("people"):
                    if st.button(
                        "Pause check-ins" if person["active"] else "Restore check-ins",
                        key=f"state_{person['id']}",
                        icon=":material/pause_circle:"
                        if person["active"]
                        else ":material/play_circle:",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        confirmation(
                            "Change check-in access?",
                            "Saved attendance and face enrollment remain available.",
                            change_status,
                            args=(person,),
                        )
                if can("privacy"):
                    with st.container(key=f"person_delete_{person['id']}"):
                        if st.button(
                            "Delete person",
                            key=f"delete_directory_{person['id']}",
                            icon=":material/delete:",
                            type="tertiary",
                            use_container_width=True,
                        ):
                            confirmation(
                                "Delete " + person["full_name"] + "?",
                                "This removes the person from active attendance and erases saved face data. Past attendance is retained.",
                                delete_selected_person,
                                args=(person["id"], PAGE_CATEGORIES.get(category, "Other people")),
                            )
    previous, caption, next_page = st.columns([1, 3, 1])
    if previous.button("Previous", disabled=page == 1, key=scope + "_prev"):
        st.session_state[scope + "_page"] = page - 1
        st.rerun()
    caption.caption(f"Page {page} of {max(1, (response['total'] + 19) // 20)}")
    if next_page.button("Next", disabled=page * 20 >= response["total"], key=scope + "_next"):
        st.session_state[scope + "_page"] = page + 1
        st.rerun()


def edit_profile(person, institutional=False):
    data = profile_data(person)
    catalog = request("GET", "/catalog")
    scope = f"profile_edit_{person['id']}_{institutional}"
    reset_button(scope, label="Reset unsaved changes")
    with st.form(control_key(scope, "form")):
        a, b = st.columns(2)
        if institutional:
            with a:
                data["department_id"] = catalog_picker(
                    "Department", "department", catalog, person["department_id"]
                )
                data["joined_on"] = st.date_input(
                    "Joining date", date.fromisoformat(person["joined_on"])
                ).isoformat()
            details = dict(person["details"])
            with b:
                if person["category"] == "student":
                    details["class_id"] = catalog_picker(
                        "Class", "class", catalog, details["class_id"]
                    )
                    details["section"] = st.text_input("Section", details["section"] or "") or None
                else:
                    details["designation"] = (
                        st.text_input("Job title / designation", details["designation"] or "")
                        or None
                    )
                    details["shift_id"] = catalog_picker(
                        "Shift", "shift", catalog, details["shift_id"]
                    )
            if person["category"] == "student":
                a, b, c = st.columns(3)
                details["academic_year"] = (
                    a.text_input("Academic session", details["academic_year"] or "") or None
                )
                details["semester"] = b.text_input("Semester", details["semester"] or "") or None
                details["roll_number"] = (
                    c.text_input("Roll number", details["roll_number"] or "") or None
                )
            elif person["category"] == "teacher":
                courses = {
                    entry["id"]: entry["name"] for entry in catalog if entry["kind"] == "course"
                }
                details["assigned_courses"] = st.multiselect(
                    "Assigned courses",
                    list(courses),
                    default=details["assigned_courses"],
                    format_func=courses.get,
                )
            data["details"] = details
        else:
            data["full_name"] = a.text_input("Full name", person["full_name"])
            data["institutional_id"] = b.text_input("Institutional ID", person["institutional_id"])
            data["age"] = a.number_input(
                "Age (years)", min_value=0, max_value=120, value=person["age"], step=1
            )
            data["email"] = b.text_input("Email", person["email"] or "") or None
            data["phone"] = a.text_input("Phone", person["phone"] or "") or None
            if person["category"] == "other":
                data["custom_type"] = (
                    b.text_input("Person type", person["custom_type"] or "") or None
                )
            data["notes"] = st.text_area("Notes", person["notes"])
        if st.form_submit_button("Save profile", type="primary"):
            values = validate_person(data)
            if values:
                request("PUT", f"/people/{person['id']}", json=values)
                st.session_state.notice = "Profile updated."
                st.rerun()


def profile(category, person_id):
    person = request("GET", f"/people/{person_id}", params={"category": category})
    if st.button("Back to directory", icon=":material/arrow_back:"):
        st.session_state.pop("profile_id", None)
        st.rerun()
    a, b = st.columns([4, 1])
    with a:
        person_identity(person)
    with b:
        badge("Active" if person["active"] else "Paused", "good" if person["active"] else "muted")
    tabs = ["Overview", "Personal info", "Institution", "Attendance"]
    if can("enroll"):
        tabs.append("Face enrollment")
    if can("audit"):
        tabs.append("Activity")
    selected = option_buttons("", tabs, key=f"profile_tab_{person_id}")
    if selected == "Overview":
        left, right = st.columns([2, 1])
        catalog = {entry["id"]: entry["name"] for entry in request("GET", "/catalog")}
        with left, st.container(border=True):
            st.subheader("Profile overview")
            for label, value in [
                ("Category", person["person_type"]),
                ("Age", person["age"]),
                ("Department", catalog.get(person["department_id"])),
                ("Joined", person["joined_on"]),
                ("Email", person["email"]),
                ("Phone", person["phone"]),
            ]:
                st.write(f"{label}: {value if value is not None else 'Not provided'}")
        with right, st.container(border=True):
            st.subheader("Face enrollment")
            badge(
                "Ready for recognition" if person["enrolled"] else "Not enrolled",
                "good" if person["enrolled"] else "warn",
            )
            if can("people"):
                try:
                    st.image(request("GET", f"/people/{person_id}/photo"), width=180)
                except APIError:
                    st.caption("No profile photo")
        if can("people"):
            with st.expander("Profile photo"):
                photo = st.file_uploader(
                    "Upload profile photo",
                    type=["jpg", "jpeg", "png"],
                    key=f"profile_photo_{person_id}",
                )
                if photo and st.button("Save profile photo"):
                    request(
                        "POST",
                        f"/people/{person_id}/photo",
                        files={"file": (photo.name, photo.getvalue())},
                    )
                    st.session_state.notice = "Profile photo saved."
                    st.rerun()
    elif selected in {"Personal info", "Institution"}:
        if can("people"):
            edit_profile(person, selected == "Institution")
        else:
            values = (
                person["details"]
                if selected == "Institution"
                else {
                    key: person[key]
                    for key in ("full_name", "institutional_id", "age", "email", "phone")
                }
            )
            st.table(
                [
                    {
                        "Field": key.replace("_", " ").title(),
                        "Value": str(value) if value is not None else "—",
                    }
                    for key, value in values.items()
                    if value
                ]
            )
    elif selected == "Attendance":
        from frontend.views.analytics import history

        view = option_buttons("", ["History", "Calendar"], key=f"profile_attendance_{person_id}")
        if view == "History":
            history(category=category, export=can("export"), person_id=person_id)
        else:
            from frontend.views.operations import calendar_view

            calendar_view(category, person_id)
        if category != "student":
            leaves = request(
                "GET", "/leaves", params={"category": category, "person_id": person_id}
            )
            st.subheader("Leave history")
            if leaves:
                st.dataframe(leaves, hide_index=True, use_container_width=True)
            else:
                st.caption("No leave records.")
    elif selected == "Face enrollment":
        from frontend.views.people import enrollment

        enrollment(person)
    else:
        rows = request("GET", f"/people/{person_id}/activity")
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        else:
            empty("No activity yet", "Profile and attendance changes will appear here.")
