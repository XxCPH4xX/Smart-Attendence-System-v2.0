from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from backend.db import utcnow
from frontend.client import people_options, person_label, request
from frontend.controls import control_key, reset_button
from frontend.design import confirmation


def create_session(category=None):
    reset_button("schedule", label="Reset session form")
    config = request("GET", "/settings")
    zone = ZoneInfo(config["timezone"])
    today = utcnow().astimezone(zone).date()
    if category is None:
        category = st.selectbox(
            "Session category",
            ["student", "teacher", "staff", "other"],
            key=control_key("schedule", "category"),
        )
    else:
        st.caption(category.title() + " sessions only")
    options = people_options(category, True)
    with st.form(control_key("schedule", "form")):
        name = st.text_input("Session name", placeholder="Class 10 · Morning attendance")
        a, b, c = st.columns(3)
        day = a.date_input("Session date", today)
        start = b.time_input("Start time", time(9))
        end = c.time_input("End time", time(17))
        overnight = st.checkbox("End on the following day (overnight shift)")
        a, b = st.columns(2)
        cutoff = a.time_input("Check-in cutoff", time(10))
        grace = b.number_input("Grace period (minutes)", min_value=0, max_value=180, value=10)
        checkout = st.checkbox("Allow authorized manual checkout")
        roster = st.multiselect(
            "Assigned people", list(options), format_func=lambda i: person_label(options[i])
        )
        if st.form_submit_button("Create attendance session", type="primary"):
            start_dt = datetime.combine(day, start, zone)
            end_dt = datetime.combine(day + timedelta(days=int(overnight)), end, zone)
            cutoff_day = day + timedelta(days=int(overnight and cutoff < start))
            result = request(
                "POST",
                "/sessions",
                json={
                    "name": name,
                    "category": category,
                    "timezone": str(zone),
                    "starts_at": start_dt.isoformat(),
                    "ends_at": end_dt.isoformat(),
                    "cutoff_at": datetime.combine(cutoff_day, cutoff, zone).isoformat(),
                    "grace_minutes": grace,
                    "checkout_enabled": checkout,
                    "person_ids": roster,
                },
            )
            st.success(f"Session #{result['id']} created with an explicit roster")


def finalize_sessions(category=None):
    sessions = request("GET", "/sessions", params={"category": category} if category else {})
    reset_button("finalize", label="Reset selection")
    candidates = {
        s["id"]: s
        for s in sessions
        if not s["finalized"]
        and not s.get("station")
        and datetime.fromisoformat(s["ends_at"]) < utcnow()
    }
    st.write(
        "After a session ends, finalize it to create absent, approved leave, or holiday records for roster members without a record. Pending recognition stays pending."
    )
    if candidates:
        selected = st.selectbox(
            "Session to finalize",
            list(candidates),
            format_func=lambda i: f"#{i} · {candidates[i]['name']} · {candidates[i]['local_date']}",
            key=control_key("finalize", "session"),
        )
        if st.button("Finalize ended session"):
            result = request("POST", f"/sessions/{selected}/finalize")
            st.success(f"Added {result['records_added']} attendance records")
    else:
        st.info("No unfinalized sessions.")


def leave_forms(category=None):
    reset_button("leave", label="Reset leave form")
    entries = request("GET", "/leaves", params={"category": category} if category else {})
    st.dataframe(entries, hide_index=True, use_container_width=True)
    options = people_options(category, True)
    if options:
        with st.form(control_key("leave", "form")):
            person_id = st.selectbox(
                "Person", list(options), format_func=lambda i: person_label(options[i])
            )
            a, b = st.columns(2)
            starts = a.date_input("Leave from")
            ends = b.date_input("Leave through")
            reason = st.text_input("Leave reason")
            if st.form_submit_button("Approve leave"):
                request(
                    "POST",
                    "/leaves",
                    json={
                        "person_id": person_id,
                        "starts_on": starts.isoformat(),
                        "ends_on": ends.isoformat(),
                        "reason": reason,
                    },
                )
                st.rerun()
    if entries:
        with st.container(border=True):
            choices = {entry["id"]: entry for entry in entries}
            people = people_options(category)
            leave_id = st.selectbox(
                "Leave to revoke",
                list(choices),
                format_func=lambda key: f"{person_label(people[choices[key]['person_id']])} · {choices[key]['starts_on']} to {choices[key]['ends_on']}",
                key=control_key("leave", "id"),
            )
            reason = st.text_input("Revocation reason", key=control_key("leave", "reason"))
            if st.button("Revoke leave record"):
                confirmation(
                    "Revoke approved leave?",
                    "Existing attendance stays unchanged.",
                    request,
                    args=("DELETE", f"/leaves/{leave_id}"),
                    kwargs={"json": {"reason": reason}},
                )
    st.caption(
        "Changing leave or holidays does not rewrite existing attendance; use Attendance Operations → Corrections for those records."
    )


def holiday_forms(category=None):
    reset_button("holiday", label="Reset holiday form")
    holidays = request("GET", "/holidays")
    st.dataframe(holidays, hide_index=True)
    with st.form(control_key("holiday", "form")):
        day = st.date_input("Holiday date")
        name = st.text_input("Holiday name")
        if st.form_submit_button("Save holiday"):
            request("POST", "/holidays", json={"day": day.isoformat(), "name": name})
            st.rerun()
    if holidays:
        remove = st.selectbox(
            "Holiday to remove",
            [h["day"] for h in holidays],
            key=control_key("holiday", "selected"),
        )
        if st.button("Remove holiday"):
            confirmation(
                "Remove holiday?",
                "Existing attendance stays unchanged.",
                request,
                args=("DELETE", f"/holidays/{remove}"),
            )


def organization(category=None):
    kinds = {
        "student": ["department", "class"],
        "teacher": ["department", "course"],
        "staff": ["department", "shift"],
    }.get(category, ["department", "class", "course", "shift"])
    reset_button("catalog", label="Reset organization form")
    st.caption(
        "Catalog entries describe departments, classes, courses and shift names. Session start/end times and explicit rosters determine attendance rules."
    )
    catalog = [entry for entry in request("GET", "/catalog") if entry["kind"] in kinds]
    st.dataframe(catalog, hide_index=True, use_container_width=True)
    with st.form(control_key("catalog", "form")):
        kind = st.selectbox("Type", kinds)
        name = st.text_input("Name")
        description = st.text_input("Description (optional)")
        if st.form_submit_button("Add catalog entry"):
            request(
                "POST",
                "/catalog",
                json={"kind": kind, "name": name, "details": {"description": description}},
            )
            st.rerun()
    if catalog:
        selected = st.selectbox(
            "Edit catalog entry",
            catalog,
            format_func=lambda c: f"{c['kind']} · {c['name']}",
            key=control_key("catalog", "selected"),
        )
        updated_name = st.text_input(
            "Updated name",
            selected["name"],
            key=control_key("catalog", f"name_{selected['id']}"),
        )
        if st.button("Rename entry"):
            request(
                "PUT",
                f"/catalog/{selected['id']}",
                json={
                    "kind": selected["kind"],
                    "name": updated_name,
                    "details": selected["details"],
                },
            )
            st.rerun()


def form_timestamp(day, clock, original):
    chosen = datetime.combine(day, clock, original.tzinfo)
    # The time widget only represents minutes; preserve seconds when the time is unchanged.
    if chosen.replace(second=0, microsecond=0) == original.replace(second=0, microsecond=0):
        return original.isoformat()
    return chosen.isoformat()


def corrections():
    reset_button("corrections", label="Reset correction form")
    sessions = {s["id"]: s for s in request("GET", "/sessions")}
    if not sessions:
        st.info("Create an attendance session with an assigned roster first.")
        return
    selected = st.selectbox(
        "Attendance session",
        list(sessions),
        format_func=lambda i: f"#{i} · {sessions[i]['name']} · {sessions[i]['local_date']}",
        key=control_key("corrections", "session"),
    )
    session = sessions[selected]
    rows = request(
        "GET", "/attendance", params={"start": session["local_date"], "end": session["local_date"]}
    )
    rows = [r for r in rows if r["session_id"] == selected]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    pending = {r["record_id"]: r for r in rows if r["verification"] == "pending"}
    if pending:
        st.subheader("Verify camera attendance")
        with st.form(control_key("corrections", "approve")):
            record_id = st.selectbox(
                "Pending record",
                list(pending),
                format_func=lambda i: f"{pending[i]['full_name']} · {pending[i]['check_in']}",
            )
            reason = st.text_input(
                "Verification evidence", placeholder="Checked in person by the attendance desk"
            )
            if st.form_submit_button("Approve attendance"):
                request("POST", f"/attendance/{record_id}/approve", json={"reason": reason})
                st.rerun()
    st.subheader("Manual attendance or correction")
    st.caption(
        "Use this form for non-biometric attendance, rejected recognition, exceptions, and authorized checkout. Every change keeps the previous value and your reason in the audit log."
    )
    members = request("GET", f"/sessions/{selected}/roster")
    options = people_options(None if session.get("station") else session["category"])
    options = {i: p for i, p in options.items() if i in members}
    if not options:
        return
    person_id = st.selectbox(
        "Roster member",
        list(options),
        format_func=lambda i: person_label(options[i]),
        key=control_key("corrections", f"person_{selected}"),
    )
    existing = next(
        (r for r in rows if r["institutional_id"] == options[person_id]["institutional_id"]), None
    )
    statuses = [
        "present",
        "late",
        "absent",
        "excused",
        "on_leave",
        "holiday",
        "pending_verification",
    ]
    status = st.selectbox(
        "Attendance status",
        statuses,
        index=statuses.index(existing["status"]) if existing else 0,
        format_func=lambda value: value.replace("_", " ").title(),
        key=control_key("corrections", f"status_{selected}_{person_id}"),
    )
    zone = ZoneInfo(session["timezone"])
    attending = status in {"present", "late", "pending_verification"}
    default_in = datetime.fromisoformat(
        existing["check_in"] if existing and existing["check_in"] else session["starts_at"]
    ).astimezone(zone)
    now = utcnow().astimezone(zone)
    if not existing and session.get("station") and session["local_date"] == now.date().isoformat():
        default_in = now.replace(microsecond=0)
    default_out = datetime.fromisoformat(
        existing["check_out"] if existing and existing["check_out"] else session["ends_at"]
    ).astimezone(zone)
    checkout = (
        attending
        and session["checkout_enabled"]
        and st.checkbox(
            "Include checkout time",
            bool(existing and existing["check_out"]),
            key=control_key("corrections", f"checkout_{selected}_{person_id}"),
        )
    )
    with st.form(control_key("corrections", f"form_{selected}_{person_id}")):
        check_in = check_out = None
        if attending:
            a, b = st.columns(2)
            in_date = a.date_input("Check-in date", default_in.date())
            in_time = b.time_input("Check-in time", default_in.time(), step=60)
            check_in = form_timestamp(in_date, in_time, default_in)
        if checkout:
            a, b = st.columns(2)
            out_date = a.date_input("Check-out date", default_out.date())
            out_time = b.time_input("Check-out time", default_out.time(), step=60)
            check_out = form_timestamp(out_date, out_time, default_out)
        st.caption(f"Times use {session['timezone']}.")
        reason = st.text_area("Why are you recording or changing this attendance?")
        if st.form_submit_button("Save attendance", type="primary"):
            request(
                "POST",
                "/attendance/correct",
                json={
                    "session_id": selected,
                    "person_id": person_id,
                    "status": status,
                    "check_in": check_in,
                    "check_out": check_out,
                    "reason": reason,
                    "expected_version": existing["version"] if existing else 0,
                },
            )
            st.session_state.notice = "Attendance saved with a record of your changes."
            st.rerun()
