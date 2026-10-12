import streamlit as st

from frontend.client import APIError, can, clear_session, request
from frontend.navigation import navigate
from frontend.views import administration, analytics, home, live, people, schedules

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
        with st.expander("First time here?"):
            st.write("Create your first administrator account from the project terminal.")
            st.code("./.venv/bin/attendance create-admin", language="bash")


def settings():
    options = {"My account": administration.account}
    if can("schedule"):
        options["Schedules & organization"] = schedules.render
    if can("settings"):
        options["Camera settings"] = lambda: administration.settings(False)
        options["Working days & retention"] = lambda: administration.settings(True)
    if can("users"):
        options["Login accounts"] = administration.users
    if can("audit"):
        options["Change history"] = administration.audit
    options["Recognition evaluation"] = administration.evaluation
    selected = st.selectbox("Manage", list(options), key="settings_section")
    options[selected]()


def main():
    if not st.session_state.get("token"):
        sign_in()
        return
    st.session_state.user = request("GET", "/auth/me")
    pending = st.session_state.pop("navigation_request", None)
    if pending:
        navigate(*pending)
    pages = ["Home", "People"]
    if can("camera"):
        pages.append("Take attendance")
    pages += ["Records", "Settings"]
    if st.session_state.get("page") not in pages:
        st.session_state.page = "Home"
    with st.sidebar:
        st.title("Attendance")
        st.caption("Signed in as " + st.session_state.user["username"])
        selected = st.radio("Workspace", pages, key="page", label_visibility="collapsed")
        st.divider()
        st.caption("Add a person → Add their face → Take attendance")
        if st.button("Sign out", use_container_width=True):
            request("POST", "/auth/logout")
            clear_session()
            st.rerun()
    if selected != "Take attendance" and st.session_state.get("stream_id"):
        if st.session_state.get("processor"):
            st.session_state.processor.close()
            st.session_state.pop("processor", None)
        else:
            request("DELETE", f"/vision/streams/{st.session_state.stream_id}")
        st.session_state.pop("stream_id", None)
        st.session_state.pop("was_playing", None)
    st.title(selected)
    message = st.session_state.pop("notice", None)
    if message:
        st.success(message)
    if selected == "Home":
        home.render()
    elif selected == "People":
        people.render()
    elif selected == "Take attendance":
        live.render()
    elif selected == "Records":
        options = ["Attendance history"]
        if can("correct"):
            options.append("Review & correct")
        selected_view = st.radio("Show", options, horizontal=True, key="records_view")
        if selected_view == "Review & correct":
            schedules.corrections()
        else:
            analytics.history(export=can("export"))
    else:
        settings()


try:
    main()
except APIError as error:
    st.error(str(error))
