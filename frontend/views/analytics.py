from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.db import utcnow
from frontend.attendance_actions import delete_attendance, recovery_controls
from frontend.client import can, people_options, person_label, request
from frontend.controls import control_key, delete_person_button, reset_button
from frontend.navigation import navigate

COLORS = {
    "present": "#246B5B",
    "late": "#B48327",
    "absent": "#AC5252",
    "pending_verification": "#73899D",
    "on_leave": "#846BAD",
    "excused": "#68A0A4",
    "holiday": "#8C939A",
}


def trends(rows):
    if not rows:
        st.info(
            "No attendance records in this period. Create a session and record attendance to see trends."
        )
        return
    frame = pd.DataFrame(rows)
    a, b = st.columns(2)
    daily = frame.groupby(["date", "status"]).size().reset_index(name="Records")
    a.plotly_chart(
        px.bar(
            daily,
            x="date",
            y="Records",
            color="status",
            color_discrete_map=COLORS,
            title="Attendance by day",
        ),
        use_container_width=True,
    )
    categories = frame.groupby(["person_type", "status"]).size().reset_index(name="Records")
    b.plotly_chart(
        px.bar(
            categories,
            x="person_type",
            y="Records",
            color="status",
            color_discrete_map=COLORS,
            title="Attendance by category",
        ),
        use_container_width=True,
    )
    a, b = st.columns(2)
    departments = frame.groupby(["department", "status"]).size().reset_index(name="Records")
    a.plotly_chart(
        px.bar(
            departments,
            x="department",
            y="Records",
            color="status",
            color_discrete_map=COLORS,
            title="Attendance by department",
        ),
        use_container_width=True,
    )
    status = frame.groupby("status").size().reset_index(name="Records")
    b.plotly_chart(
        px.pie(
            status,
            names="status",
            values="Records",
            color="status",
            color_discrete_map=COLORS,
            title="Recorded attendance states",
        ),
        use_container_width=True,
    )
    frequency = st.selectbox(
        "Trend interval", ["Weekly", "Monthly"], key=control_key("history", "trend")
    )
    frame["period"] = (
        pd.to_datetime(frame["date"])
        .dt.to_period("W" if frequency == "Weekly" else "M")
        .dt.start_time
    )
    grouped = frame.groupby(["period", "status"]).size().reset_index(name="Records")
    st.plotly_chart(
        px.line(
            grouped,
            x="period",
            y="Records",
            color="status",
            markers=True,
            color_discrete_map=COLORS,
            title=f"{frequency} attendance, including late arrivals",
        ),
        use_container_width=True,
    )


def history(category=None, export=False):
    scope = "history"
    actions = st.container()
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    period_column, type_column = st.columns(2)
    period = period_column.selectbox(
        "Show attendance for",
        ["Today", "This week", "This month", "Custom dates"],
        key=control_key(scope, "period"),
    )
    start = (
        today
        if period == "Today"
        else today - timedelta(days=today.weekday())
        if period == "This week"
        else today.replace(day=1)
    )
    end = today
    if period == "Custom dates":
        a, b = st.columns(2)
        start = a.date_input("From", today.replace(day=1), key=control_key(scope, "start"))
        end = b.date_input("Through", today, key=control_key(scope, "end"))
    params = {"start": start.isoformat(), "end": end.isoformat()}
    if category:
        params["category"] = category
    else:
        selected = type_column.selectbox(
            "Category",
            ["All", *request("GET", "/people/types")],
            key=control_key(scope, "category"),
        )
        if selected != "All":
            params["person_type"] = selected
    with st.expander("Filter by person, department or class"):
        catalog = request("GET", "/catalog")
        a, b, c = st.columns(3)
        departments = {
            None: "All departments",
            **{e["id"]: e["name"] for e in catalog if e["kind"] == "department"},
        }
        department = a.selectbox(
            "Department",
            list(departments),
            format_func=departments.get,
            key=control_key(scope, "department"),
        )
        classes = {
            None: "All classes",
            **{e["id"]: e["name"] for e in catalog if e["kind"] == "class"},
        }
        class_id = b.selectbox(
            "Class / program",
            list(classes),
            format_func=classes.get,
            key=control_key(scope, "class"),
        )
        section = c.text_input("Section", key=control_key(scope, "section"))
        for key, value in [
            ("department_id", department),
            ("class_id", class_id),
            ("section", section or None),
        ]:
            if value is not None:
                params[key] = value
        options = people_options(category)
        selected_person = st.selectbox(
            "Individual",
            [None, *options],
            format_func=lambda i: "All people" if i is None else person_label(options[i]),
            key=control_key(scope, "individual"),
        )
        if selected_person:
            params["person_id"] = selected_person
    rows = request("GET", "/attendance", params=params)
    with actions:
        reset, clear = st.columns(2)
        if can("delete_attendance"):
            reset.button(
                "Reset attendance",
                on_click=delete_attendance,
                kwargs={"params": params},
                disabled=not rows,
                help="Clear attendance matching the selected dates and filters. Registered people and saved faces stay available.",
            )
        with clear:
            reset_button(scope, label="Clear filters")
    st.caption(f"{len(rows)} attendance records · {start} to {end}")
    if rows:
        pages = (len(rows) + 24) // 25
        page_key = control_key(scope, "records_page")
        if st.session_state.get(page_key, 1) > pages:
            st.session_state[page_key] = 1
        page = (
            st.number_input("Records page", min_value=1, max_value=pages, step=1, key=page_key)
            if pages > 1
            else 1
        )
        for row in rows[(page - 1) * 25 : page * 25]:
            with st.container(border=True):
                person_column, session_column, status_column, action_column = st.columns(
                    [2, 1.6, 1.4, 1.1]
                )
                person_column.text(row["full_name"])
                person_column.caption(f"{row['institutional_id']} · {row['person_type']}")
                session_column.text(row["date"])
                session_column.caption(row["session"])
                status_column.text(row["status"].replace("_", " ").title())
                if row["check_in"]:
                    status_column.caption(
                        "In: " + datetime.fromisoformat(row["check_in"]).strftime("%I:%M %p")
                    )
                if row["check_out"]:
                    status_column.caption(
                        "Out: " + datetime.fromisoformat(row["check_out"]).strftime("%I:%M %p")
                    )
                if can("delete_attendance"):
                    action_column.button(
                        "Delete record",
                        key=f"delete_record_{row['record_id']}",
                        on_click=delete_attendance,
                        kwargs={"record": row},
                        help=f"Delete this attendance entry for {row['full_name']}",
                        use_container_width=True,
                    )
    row_ids = [row["person_id"] for row in rows]
    people = {i: options[i] for i in dict.fromkeys(row_ids) if i in options}
    picker_key = control_key(scope, "person")
    if st.session_state.get(picker_key) not in people:
        st.session_state[picker_key] = None
    selected_id = None
    if people:
        with st.expander("Open or manage a person's profile"):
            selected_id = st.selectbox(
                "Selected person",
                list(people),
                index=None,
                placeholder="Choose a person",
                format_func=lambda key: person_label(people[key]),
                key=picker_key,
            )
    if selected_id is not None:
        st.button(
            "Open person details", on_click=navigate, args=("People", selected_id, "Find people")
        )
        if can("privacy") and people[selected_id]["active"]:
            delete_person_button(people[selected_id], "Records")
    if not rows:
        st.info("No attendance recorded for these filters yet.")
    counted = [r for r in rows if r["status"] in {"present", "late", "absent"}]
    rate = (
        100 * sum(r["status"] in {"present", "late"} for r in counted) / len(counted)
        if counted
        else 0
    )
    st.metric("Recorded attendance rate", f"{rate:.1f}%")
    st.caption(
        "Rate = (present + late) / (present + late + finalized absent). Present includes automatic face matches. Pending, leave, excused, holidays and unfinalized missing records are excluded."
    )
    if rows:
        with st.expander("Charts and trends"):
            trends(rows)
    if can("delete_attendance"):
        recovery_controls()
    if can("export") and (export or rows):
        kind = st.selectbox(
            "Export format", ["csv", "xlsx", "pdf"], key=control_key(scope, "export")
        )
        if st.button("Prepare report"):
            content = request("GET", "/reports/export", params={**params, "kind": kind})
            st.download_button(
                "Download report", content, file_name=f"attendance-{start}-{end}.{kind}"
            )
