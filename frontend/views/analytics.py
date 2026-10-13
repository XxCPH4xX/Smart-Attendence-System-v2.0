from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.db import utcnow
from frontend.client import can, people_options, person_label, request
from frontend.controls import control_key, delete_person_button, people_table, reset_button
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
    categories = frame.groupby(["category", "status"]).size().reset_index(name="Records")
    b.plotly_chart(
        px.bar(
            categories,
            x="category",
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
    reset_button(scope, label="Reset filters")
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    period = st.selectbox(
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
        selected = st.selectbox(
            "Category",
            ["All", "student", "teacher", "staff", "other"],
            key=control_key(scope, "category"),
        )
        if selected != "All":
            params["category"] = selected
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
    labels = {
        "full_name": "Name",
        "institutional_id": "ID",
        "category": "Type",
        "date": "Date",
        "session": "Session",
        "status": "Attendance",
        "check_in": "Check-in",
        "check_out": "Check-out",
    }
    display_rows = [
        {
            label: row[key].replace("_", " ").title() if key in {"category", "status"} else row[key]
            for key, label in labels.items()
        }
        for row in rows
    ]
    row_ids = [row["person_id"] for row in rows]
    people = {i: options[i] for i in dict.fromkeys(row_ids) if i in options}
    selected_id = people_table(display_rows, row_ids, people, scope)
    if selected_id is not None:
        st.button(
            "Open person details", on_click=navigate, args=("People", selected_id, "Find people")
        )
        if can("privacy") and people[selected_id]["active"]:
            delete_person_button(people[selected_id], "Records")
    if not rows:
        st.info("No attendance recorded for these filters yet.")
    if rows:
        counted = [r for r in rows if r["status"] in {"present", "late", "absent"}]
        if counted:
            rate = 100 * sum(r["status"] in {"present", "late"} for r in counted) / len(counted)
            st.metric("Recorded attendance rate", f"{rate:.1f}%")
        st.caption(
            "Rate = (present + late) / (present + late + finalized absent). Present includes automatic face matches. Pending, leave, excused, holidays and unfinalized missing records are excluded."
        )
        with st.expander("Charts and trends"):
            trends(rows)
    if can("export") and (export or rows):
        kind = st.selectbox(
            "Export format", ["csv", "xlsx", "pdf"], key=control_key(scope, "export")
        )
        if st.button("Prepare report"):
            content = request("GET", "/reports/export", params={**params, "kind": kind})
            st.download_button(
                "Download report", content, file_name=f"attendance-{start}-{end}.{kind}"
            )
