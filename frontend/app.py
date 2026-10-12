import streamlit as st

from frontend.client import APIError, can, clear_session, request
from frontend.views import administration, analytics, live, people, schedules

st.set_page_config(page_title="Smart Attendance", page_icon="◉", layout="wide")


def sign_in():
    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.title("Smart Attendance")
        st.write("Sign in to your institution’s attendance office.")
        with st.form("login"):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            result = request(
                "POST", "/auth/login", json={"username": username, "password": password}
            )
            st.session_state.token = result["token"]
            st.session_state.user = result["user"]
            st.rerun()
        st.caption(
            "Initial setup: run attendance init, then attendance create-admin in the project terminal."
        )


def main():
    if not st.session_state.get("token"):
        sign_in()
        return
    st.session_state.user = request("GET", "/auth/me")
    with st.sidebar:
        st.title("Attendance Office")
        st.caption(
            st.session_state.user["username"]
            + " · "
            + st.session_state.user["role"].replace("_", " ").title()
        )
        pages = ["Overview"]
        for name, permission in [("Live Recognition", "camera"), ("Register Person", "people")]:
            if can(permission):
                pages.append(name)
        pages += [
            "Manage People",
            "Student Attendance",
            "Teacher Attendance",
            "Staff Attendance",
            "Attendance History",
        ]
        for name, permission in [
            ("Sessions & Schedules", "schedule"),
            ("Manual Corrections", "correct"),
            ("Reports", "export"),
            ("Recognition Evaluation", "read"),
            ("Camera & Recognition Settings", "settings"),
            ("User Management", "users"),
            ("Audit Logs", "audit"),
            ("System Settings", "settings"),
        ]:
            if can(permission):
                pages.append(name)
        pages.append("My Account")
        selected = st.radio("Workspace", pages, label_visibility="collapsed")
        if st.button("Sign out", use_container_width=True):
            request("POST", "/auth/logout")
            clear_session()
            st.rerun()
    if selected != "Live Recognition" and st.session_state.get("processor"):
        st.session_state.processor.close()
        st.session_state.pop("processor", None)
        st.session_state.pop("stream_id", None)
    st.title(selected)
    if selected == "Overview":
        analytics.overview()
    elif selected == "Register Person":
        people.register()
    elif selected == "Manage People":
        people.manage()
    elif selected == "Live Recognition":
        live.render()
    elif selected in {
        "Student Attendance",
        "Teacher Attendance",
        "Staff Attendance",
        "Attendance History",
        "Reports",
    }:
        category = {
            "Student Attendance": "student",
            "Teacher Attendance": "teacher",
            "Staff Attendance": "staff",
        }.get(selected)
        analytics.history(category, selected == "Reports")
    elif selected == "Sessions & Schedules":
        schedules.render()
    elif selected == "Manual Corrections":
        schedules.corrections()
    elif selected == "User Management":
        administration.users()
    elif selected == "Audit Logs":
        administration.audit()
    elif selected == "Recognition Evaluation":
        administration.evaluation()
    elif selected == "My Account":
        administration.account()
    else:
        administration.settings(selected == "System Settings")


try:
    main()
except APIError as error:
    st.error(str(error))
