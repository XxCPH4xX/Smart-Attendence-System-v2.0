import calendar
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from backend.db import utcnow
from frontend.attendance_actions import delete_attendance, recovery_controls
from frontend.client import can, request
from frontend.design import badge, confirmation, empty
from frontend.navigation import section_tabs
from frontend.views import schedules


def calendar_view(category=None, person_id=None):
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    month = st.date_input(
        "Calendar month", today.replace(day=1), key=f"calendar_month_{category}_{person_id}"
    )
    start = month.replace(day=1)
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    params = {"start": start.isoformat(), "end": end.isoformat()}
    if category:
        params["category"] = category
    if person_id is not None:
        params["person_id"] = person_id
    rows = request("GET", "/attendance", params=params)
    counts = defaultdict(set)
    for row in rows:
        if row["status"] in {"present", "late"}:
            counts[row["date"]].add(row["person_id"])
    weeks = calendar.Calendar().monthdayscalendar(month.year, month.month)
    cells = "".join(
        f'<div style="padding:.7rem;color:#8995aa;font-size:.75rem">{day}</div>'
        for day in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    )
    for week in weeks:
        for day in week:
            if day:
                key = date(month.year, month.month, day).isoformat()
                count = len(counts[key])
                cells += f'<div style="background:white;border:1px solid #e8edf5;border-radius:8px;padding:12px;min-height:76px"><strong>{day}</strong><div style="font-size:.72rem;color:{"#16856b" if count else "#a1aaba"};margin-top:6px">{count} checked in</div></div>'
            else:
                cells += "<div></div>"
    st.html(
        f'<div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:1rem">{cells}</div>'
    )
    selected = st.date_input(
        "Inspect attendance on",
        min_value=start,
        max_value=end,
        value=min(max(today, start), end),
        key=f"calendar_day_{category}_{person_id}_{start}",
    )
    selected_rows = [row for row in rows if row["date"] == selected.isoformat()]
    if selected_rows:
        st.dataframe(
            [
                {
                    "Name": row["full_name"],
                    "ID": row["institutional_id"],
                    "Category": row["person_type"],
                    "Session": row["session"],
                    "Status": row["status"].replace("_", " ").title(),
                    "Check-in": row["check_in"],
                    "Check-out": row["check_out"],
                }
                for row in selected_rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption(
            "No attendance recorded for this day. Missing records are not treated as absences."
        )


def pending_reviews():
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    day = st.date_input("Review attendance for", today)
    rows = request(
        "GET",
        "/attendance",
        params={"start": day.isoformat(), "end": day.isoformat(), "status": "pending_verification"},
    )
    if not rows:
        empty("All caught up", "No attendance check-ins need review for this date.")
        return
    st.caption(f"{len(rows)} check-ins need independent verification.")
    for row in rows:
        with st.container(border=True):
            st.subheader(row["full_name"])
            st.caption(f"{row['institutional_id']} · {row['person_type']} · {row['session']}")
            st.write("Check-in: " + datetime.fromisoformat(row["check_in"]).strftime("%I:%M %p"))
            if can("correct"):
                with st.form(f"approve_{row['record_id']}"):
                    reason = st.text_input(
                        "Verification evidence",
                        placeholder="Confirmed in person by the attendance desk",
                    )
                    if st.form_submit_button("Approve check-in", type="primary"):
                        request(
                            "POST",
                            f"/attendance/{row['record_id']}/approve",
                            json={"reason": reason},
                        )
                        st.session_state.notice = "Attendance verified."
                        st.rerun()


def remove_session(session_id):
    from frontend.views.live import stop_stream

    request("DELETE", f"/sessions/{session_id}")
    stop_stream()
    st.session_state.notice = "Session removed. Attendance history is kept in Reports."


def restore_session(session_id):
    request("POST", f"/sessions/{session_id}/restore")
    st.session_state.notice = "Session restored. Start its camera when ready."


def confirm_session_reset(session):
    confirmation(
        "Reset this session's attendance?",
        f"Clear attendance for {session['name']} ({session['local_date']}) and stop its camera. "
        "The schedule, roster, people and faces are kept. Cleared attendance can be restored for 30 days.",
        delete_attendance,
        kwargs={
            "params": {
                "start": session["local_date"],
                "end": session["local_date"],
                "session_id": session["id"],
            }
        },
    )


def session_list(category=None):
    removed = st.checkbox("Show removed sessions", key=f"removed_sessions_{category}")
    params = {"archived": removed}
    if category:
        params["category"] = category
    sessions = request("GET", "/sessions", params=params)
    now = utcnow()
    if not sessions:
        empty(
            "No removed sessions" if removed else "No sessions yet",
            "Removed sessions can be restored here."
            if removed
            else "Create a class or shift session, or start the shared daily station.",
        )
    for session in sessions[:30]:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.write(session["name"])
            a.caption(
                f"{session['local_date']} · {'Shared daily station' if session['station'] else session['category'].title()} · {session['timezone']}"
            )
            a.caption(f"{session.get('record_count', 0)} attendance records")
            state = (
                "Removed"
                if session.get("archived")
                else "Finalized"
                if session["finalized"]
                else "Upcoming"
                if datetime.fromisoformat(session["starts_at"]) > now
                else "Ended"
                if datetime.fromisoformat(session["ends_at"]) < now
                else "Open"
            )
            with b:
                badge(state, "good" if state == "Open" else "muted")
            actions = st.columns([1, 1, 2])
            if can("delete_attendance"):
                actions[0].button(
                    "Reset attendance",
                    key=f"reset_session_{session['id']}",
                    on_click=confirm_session_reset,
                    args=(session,),
                )
            if can("schedule"):
                if removed:
                    actions[1].button(
                        "Restore session",
                        key=f"restore_session_{session['id']}",
                        on_click=restore_session,
                        args=(session["id"],),
                    )
                else:
                    actions[1].button(
                        "Remove session",
                        key=f"remove_session_{session['id']}",
                        on_click=confirmation,
                        args=(
                            "Remove this session?",
                            f"Remove {session['name']} ({session['local_date']}) from the session list and stop its camera. "
                            "Attendance history stays in Reports. You can restore it using Show removed sessions.",
                            remove_session,
                            (session["id"],),
                        ),
                    )
    if can("delete_attendance"):
        recovery_controls(category=category)
    if can("schedule"):
        with st.expander("Create a session", icon=":material/add:"):
            schedules.create_session(category)
        with st.expander("Finalize ended sessions"):
            schedules.finalize_sessions(category)


def render():
    options = ["Active sessions", "Attendance calendar"]
    if can("correct"):
        options += ["Manual attendance", "Corrections", "Pending reviews"]
    if can("schedule"):
        options += ["Leave & holidays"]
    section = section_tabs(options, "Attendance Operations")
    if section == "Active sessions":
        session_list()
    elif section == "Attendance calendar":
        calendar_view()
    elif section in {"Manual attendance", "Corrections"}:
        schedules.corrections()
    elif section == "Pending reviews":
        pending_reviews()
    else:
        with st.expander("Leave requests", expanded=True):
            schedules.leave_forms()
        with st.expander("Institution holidays"):
            schedules.holiday_forms()
