from datetime import date
from html import escape

import streamlit as st

from frontend.browser_session import restore_session, sync_browser_session
from frontend.client import APIError, can, clear_session, request
from frontend.design import apply_theme, flash, heading, render_confirmation
from frontend.navigation import CATEGORY_PAGES, open_page, section_tabs
from frontend.views import (
    administration,
    analytics,
    directory,
    enrollments,
    home,
    live,
    operations,
    schedules,
)

st.set_page_config(page_title="Smart Attendance", page_icon="◉", layout="wide")
apply_theme()

DESCRIPTIONS = {
    "Overview": ("Institution overview", "Attendance, people and daily operations in one place."),
    "Live Recognition": (
        "Live recognition",
        "One camera for everyone. Enrolled people check in as they arrive.",
    ),
    "Students": ("Students", "Student profiles, academic information and attendance."),
    "Teachers": ("Teachers", "Teacher profiles, schedules and attendance."),
    "Staff": ("Staff", "Staff profiles, shifts and attendance."),
    "Enrollment": ("Enrollment", "Register people and manage their face enrollment."),
    "Attendance Operations": (
        "Attendance operations",
        "Sessions, reviews and day-to-day attendance.",
    ),
    "Reports & Analytics": (
        "Reports & analytics",
        "Institution-wide reporting with explicit category filters.",
    ),
    "Administration": (
        "Administration",
        "Accounts, access, institution settings and audit history.",
    ),
    "System Settings": (
        "System settings",
        "Configure recognition, attendance rules and data retention.",
    ),
}
ICONS = {
    "Overview": "space_dashboard",
    "Live Recognition": "videocam",
    "Students": "school",
    "Teachers": "cast_for_education",
    "Staff": "badge",
    "Enrollment": "person_add",
    "Attendance Operations": "event_available",
    "Reports & Analytics": "bar_chart",
    "Administration": "admin_panel_settings",
    "System Settings": "settings",
}


def sign_in():
    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        st.html('<div class="sa-brand"><span class="sa-mark">◉</span>Smart Attendance</div>')
        heading(
            "Welcome back",
            "Sign in to your institution’s attendance workspace.",
            "Secure workspace",
        )
        with st.form("login"):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                result = request(
                    "POST", "/auth/login", json={"username": username, "password": password}
                )
                st.session_state.token = result["token"]
                st.session_state.user = result["user"]
                st.rerun()
        with st.expander("First-time setup"):
            st.caption("Create your administrator account in the project terminal.")
            st.code("./.venv/bin/attendance create-admin", language="bash")


def sidebar():
    with st.sidebar:
        st.html('<div class="sa-brand"><span class="sa-mark">◉</span>Smart Attendance</div>')
        groups = {
            "WORKSPACE": ["Overview", "Live Recognition"],
            "PEOPLE": ["Students", "Teachers", "Staff"],
            "OPERATIONS": ["Enrollment", "Attendance Operations", "Reports & Analytics"],
        }
        for group, pages in groups.items():
            st.html(f'<div class="sa-nav-group">{group}</div>')
            for page in pages:
                if page == "Live Recognition" and not can("camera"):
                    continue
                if page == "Enrollment" and not (can("people") or can("enroll")):
                    continue
                st.button(
                    page,
                    key="nav_" + page,
                    icon=f":material/{ICONS[page]}:",
                    type="primary" if st.session_state.page == page else "secondary",
                    use_container_width=True,
                    on_click=open_page,
                    args=(page, "Directory" if page in CATEGORY_PAGES else None),
                )
        with st.expander(
            "System", expanded=st.session_state.page in {"Administration", "System Settings"}
        ):
            for page in ["Administration", "System Settings"]:
                st.button(
                    page,
                    key="nav_" + page,
                    icon=f":material/{ICONS[page]}:",
                    type="primary" if st.session_state.page == page else "secondary",
                    use_container_width=True,
                    on_click=open_page,
                    args=(page,),
                )
        st.caption("Local workspace · Smart Attendance")


def topbar(summary):
    with st.container(key="topbar"):
        institution, notification, account = st.columns([5, 0.5, 1.5], vertical_alignment="center")
        with institution:
            st.html(
                f'<strong style="font-size:.9rem;color:#65718b">{escape(summary["institution"])}</strong>'
            )
            st.caption(date.fromisoformat(summary["date"]).strftime("%A, %d %B %Y"))
        with (
            notification,
            st.container(key="topbar_bell"),
            st.popover("Alerts", icon=":material/notifications:"),
        ):
            count = summary["attendance"].get("pending_verification", 0)
            st.write(f"{count} check-ins awaiting review today.")
            if can("correct"):
                st.button(
                    "Open pending reviews",
                    on_click=open_page,
                    args=("Attendance Operations", "Pending reviews"),
                )
            else:
                st.caption("An attendance operator can review these records.")
        user = st.session_state.user
        with (
            account,
            st.container(key="topbar_account"),
            st.popover(
                user["username"], icon=":material/account_circle:", use_container_width=True
            ),
        ):
            st.caption(user["role"].replace("_", " ").title())
            st.button("My account", on_click=open_page, args=("Administration", "My account"))
            if st.button("Sign out", icon=":material/logout:"):
                request("POST", "/auth/logout")
                clear_session()
                st.rerun()


def category_workspace(page):
    category = CATEGORY_PAGES[page]
    if (
        st.session_state.get("profile_id")
        and st.session_state.get("section_" + page, "Directory") == "Directory"
    ):
        directory.profile(category, st.session_state.profile_id)
        return
    organization = {
        "student": "Classes & sections",
        "teacher": "Departments & courses",
        "staff": "Departments & shifts",
    }[category]
    options = ["Directory", "Attendance", "Calendar", "Reports"]
    if can("schedule"):
        options += [
            organization,
            "Teaching schedules"
            if category == "teacher"
            else "Class sessions"
            if category == "student"
            else "Shifts & leave",
        ]
    selected = section_tabs(options, page)
    if selected == "Directory":
        directory.directory(category)
    elif selected in {"Attendance", "Reports"}:
        analytics.history(category=category, export=selected == "Reports")
    elif selected == "Calendar":
        operations.calendar_view(category)
    elif selected == organization:
        schedules.organization(category)
    else:
        operations.session_list(category)
        if category in {"teacher", "staff"}:
            with st.expander("Leave records"):
                schedules.leave_forms(category)


def reports():
    options = ["Attendance history", "Trends & breakdowns"]
    if can("export"):
        options.append("Export center")
    selected = section_tabs(options, "Reports & Analytics")
    if selected in {"Attendance history", "Export center"}:
        analytics.history(export=selected == "Export center")
    else:
        config = request("GET", "/settings")
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from backend.db import utcnow

        today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
        a, b, c = st.columns(3)
        start = a.date_input("From", today - timedelta(days=29))
        end = b.date_input("Through", today)
        category = c.selectbox(
            "Category", ["Institution-wide", "Students", "Teachers", "Staff", "Other"]
        )
        if end < start or (end - start).days > 366:
            st.warning("Choose dates in order, covering no more than 366 days.")
            return
        params = {"start": start.isoformat(), "end": end.isoformat()}
        if category != "Institution-wide":
            params["category"] = {
                "Students": "student",
                "Teachers": "teacher",
                "Staff": "staff",
                "Other": "other",
            }[category]
        analytics.trends(request("GET", "/attendance", params=params))


def main():
    restore_session()
    if not st.session_state.get("token"):
        sync_browser_session()
        sign_in()
        return
    st.session_state.user = request("GET", "/auth/me")
    sync_browser_session()
    aliases = {
        "Home": "Overview",
        "Take attendance": "Live Recognition",
        "People": "Enrollment",
        "Records": "Reports & Analytics",
        "Settings": "System Settings",
    }
    pending = st.session_state.pop("navigation_request", None)
    if pending:
        page, person_id, action = pending
        open_page(
            aliases.get(page, page),
            "Face enrollment"
            if action == "Enroll a face"
            else "New registration"
            if action == "Add person"
            else None,
            person_id=person_id,
        )
    page = aliases.get(st.session_state.get("page"), st.session_state.get("page", "Overview"))
    if (
        page not in DESCRIPTIONS
        or (page == "Live Recognition" and not can("camera"))
        or (page == "Enrollment" and not (can("people") or can("enroll")))
    ):
        page = "Overview"
    st.session_state.page = page
    if page != "Live Recognition" and st.session_state.get("stream_id"):
        live.stop_stream()
    sidebar()
    summary = request("GET", "/overview")
    topbar(summary)
    title, description = DESCRIPTIONS[page]
    if page == "Overview":
        description = (
            "Welcome, " + st.session_state.user["username"] + ". Here is your institution today."
        )
    heading(title, description, "Workspace / " + page)
    flash()
    if page in CATEGORY_PAGES:
        category_workspace(page)
    else:
        {
            "Overview": home.render,
            "Live Recognition": live.render,
            "Enrollment": enrollments.render,
            "Attendance Operations": operations.render,
            "Reports & Analytics": reports,
            "Administration": administration.render_admin,
            "System Settings": administration.render_system,
        }[page]()


try:
    with st.empty().container():
        main()
    render_confirmation()
except APIError as error:
    st.error(str(error))
