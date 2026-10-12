from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from backend.db import utcnow
from frontend.client import people_options, person_label, request


def render():
    sessions = request("GET", "/sessions")
    st.dataframe(sessions, hide_index=True, use_container_width=True)
    tabs = st.tabs(
        ["Create session", "Finalize session", "Leave", "Holidays", "Departments, classes & shifts"]
    )
    with tabs[0]:
        config = request("GET", "/settings")
        zone = ZoneInfo(config["timezone"])
        today = utcnow().astimezone(zone).date()
        category = st.selectbox("Session category", ["student", "teacher", "staff", "other"])
        options = people_options(category, True)
        with st.form("session"):
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
    with tabs[1]:
        candidates = {s["id"]: s for s in sessions if not s["finalized"] and not s.get("station")}
        st.write(
            "After a session ends, finalize it to create absent, approved leave, or holiday records for roster members without a record. Pending recognition stays pending."
        )
        if candidates:
            selected = st.selectbox(
                "Session to finalize",
                list(candidates),
                format_func=lambda i: f"#{i} · {candidates[i]['name']} · {candidates[i]['local_date']}",
            )
            if st.button("Finalize ended session"):
                result = request("POST", f"/sessions/{selected}/finalize")
                st.success(f"Added {result['records_added']} attendance records")
        else:
            st.info("No unfinalized sessions.")
    with tabs[2]:
        st.dataframe(request("GET", "/leaves"), hide_index=True, use_container_width=True)
        options = people_options()
        if options:
            with st.form("leave"):
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
            with st.expander("Revoke leave"):
                leave_id = st.number_input("Leave record ID", min_value=1, step=1)
                reason = st.text_input("Revocation reason")
                if st.button("Revoke leave record"):
                    request("DELETE", f"/leaves/{leave_id}", json={"reason": reason})
                    st.rerun()
        st.caption(
            "Changing leave or holidays does not rewrite existing attendance; use Records → Review & correct for those records."
        )
    with tabs[3]:
        holidays = request("GET", "/holidays")
        st.dataframe(holidays, hide_index=True)
        with st.form("holiday"):
            day = st.date_input("Holiday date")
            name = st.text_input("Holiday name")
            if st.form_submit_button("Save holiday"):
                request("POST", "/holidays", json={"day": day.isoformat(), "name": name})
                st.rerun()
        if holidays:
            remove = st.selectbox("Holiday to remove", [h["day"] for h in holidays])
            if st.button("Remove holiday"):
                request("DELETE", f"/holidays/{remove}")
                st.rerun()
    with tabs[4]:
        st.caption(
            "Catalog entries describe departments, classes, courses and shift names. Session start/end times and explicit rosters determine attendance rules."
        )
        catalog = request("GET", "/catalog")
        st.dataframe(catalog, hide_index=True, use_container_width=True)
        with st.form("catalog"):
            kind = st.selectbox("Type", ["department", "class", "course", "shift"])
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
                "Edit catalog entry", catalog, format_func=lambda c: f"{c['kind']} · {c['name']}"
            )
            updated_name = st.text_input("Updated name", selected["name"])
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


def corrections():
    sessions = {s["id"]: s for s in request("GET", "/sessions")}
    if not sessions:
        st.info("Create an attendance session with an assigned roster first.")
        return
    selected = st.selectbox(
        "Attendance session",
        list(sessions),
        format_func=lambda i: f"#{i} · {sessions[i]['name']} · {sessions[i]['local_date']}",
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
        with st.form("approve"):
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
        "Roster member", list(options), format_func=lambda i: person_label(options[i])
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
    )
    zone = ZoneInfo(session["timezone"])
    attending = status in {"present", "late", "pending_verification"}
    default_in = datetime.fromisoformat(
        existing["check_in"] if existing and existing["check_in"] else session["starts_at"]
    ).astimezone(zone)
    default_out = datetime.fromisoformat(
        existing["check_out"] if existing and existing["check_out"] else session["ends_at"]
    ).astimezone(zone)
    checkout = (
        attending
        and session["checkout_enabled"]
        and st.checkbox("Include checkout time", bool(existing and existing["check_out"]))
    )
    with st.form("correction"):
        check_in = check_out = None
        if attending:
            a, b = st.columns(2)
            in_date = a.date_input("Check-in date", default_in.date())
            in_time = b.time_input("Check-in time", default_in.time())
            check_in = datetime.combine(in_date, in_time, zone).isoformat()
        if checkout:
            a, b = st.columns(2)
            out_date = a.date_input("Check-out date", default_out.date())
            out_time = b.time_input("Check-out time", default_out.time())
            check_out = datetime.combine(out_date, out_time, zone).isoformat()
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
