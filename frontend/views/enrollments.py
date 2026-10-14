import streamlit as st

from frontend.client import can, people_options, person_label, request
from frontend.design import badge, empty
from frontend.navigation import section_tabs
from frontend.registration import begin_registration, wizard
from frontend.views import directory, people


def render():
    options = []
    if can("people"):
        options.append("New registration")
    if can("enroll"):
        options += ["Face enrollment", "Enrollment management"]
    options.append("Other people")
    section = section_tabs(options, "Enrollment")
    if section == "New registration":
        wizard()
    elif section == "Other people":
        directory.directory("other")
    elif section == "Face enrollment":
        category = st.selectbox(
            "Category", ["student", "teacher", "staff", "other"], format_func=str.title
        )
        choices = people_options(category, True)
        if not choices:
            empty(
                "No active people in this category", "Register a person before adding their face."
            )
            if can("people"):
                st.button("Register " + category, on_click=begin_registration, args=(category,))
            return
        target = st.session_state.get("selected_person")
        selected = st.selectbox(
            "Choose person",
            list(choices),
            index=list(choices).index(target) if target in choices else None,
            placeholder="Search by name or ID",
            format_func=lambda key: person_label(choices[key]),
            key="enrollment_person_" + category,
        )
        if selected is not None:
            people.enrollment(choices[selected])
    else:
        category = st.selectbox(
            "Category", ["student", "teacher", "staff", "other"], format_func=str.title
        )
        choices = people_options(category, True)
        ready = sum(person["enrolled"] for person in choices.values())
        a, b = st.columns(2)
        a.metric("Ready for recognition", ready)
        b.metric("Awaiting enrollment", len(choices) - ready)
        for person in choices.values():
            with st.container(border=True):
                a, b, c = st.columns([3, 1, 1])
                a.write(person_label(person))
                with b:
                    badge(
                        "Enrolled" if person["enrolled"] else "Not added",
                        "good" if person["enrolled"] else "warn",
                    )
                c.button(
                    "Manage face",
                    key=f"enroll_manage_{person['id']}",
                    on_click=directory.open_profile,
                    args=(category, person["id"], "Face enrollment"),
                )
        with st.expander("Test face recognition"):
            st.caption(
                "Create a clearly labeled test profile and enroll your own face with permission. A face already enrolled under another profile cannot be duplicated."
            )
            if st.button("Create or open test profile"):
                person = request("POST", "/demo/person")
                directory.open_profile("student", person["id"], "Face enrollment")
                st.rerun()
