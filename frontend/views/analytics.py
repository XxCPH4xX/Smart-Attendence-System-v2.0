from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.db import utcnow
from frontend.client import can, people_options, person_label, request

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
    frequency = st.radio("Trend interval", ["Weekly", "Monthly"], horizontal=True)
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


def overview():
    summary = request("GET", "/overview")
    st.caption(f"{summary['institution']} · {summary['date']} · {summary['timezone']}")
    people = summary["people"]
    columns = st.columns(4)
    for col, label, value in zip(
        columns,
        ["Registered people", "Students", "Teachers", "Staff / other"],
        [
            sum(people.values()),
            people.get("student", 0),
            people.get("teacher", 0),
            people.get("staff", 0) + people.get("other", 0),
        ],
        strict=True,
    ):
        col.metric(label, value)
    columns = st.columns(5)
    statuses = summary["attendance"]
    for col, label, value in zip(
        columns,
        ["Present", "Late", "Absent", "Pending verification", "Active sessions"],
        [
            statuses.get("present", 0),
            statuses.get("late", 0),
            statuses.get("absent", 0),
            statuses.get("pending_verification", 0),
            summary["active_sessions"],
        ],
        strict=True,
    ):
        col.metric(label, value)
    st.caption(
        "Attendance counts are person-session records. Absences are created only when an authorized user finalizes an ended session."
    )
    today = date.fromisoformat(summary["date"])
    trends(
        request(
            "GET",
            "/attendance",
            params={"start": (today - timedelta(days=89)).isoformat(), "end": today.isoformat()},
        )
    )


def history(category=None, export=False):
    config = request("GET", "/settings")
    today = utcnow().astimezone(ZoneInfo(config["timezone"])).date()
    a, b, c = st.columns(3)
    period = a.selectbox("Reporting period", ["Today", "This week", "This month", "Custom"])
    initial = (
        today
        if period == "Today"
        else today - timedelta(days=today.weekday())
        if period == "This week"
        else today.replace(day=1)
    )
    start = b.date_input("From", initial, disabled=period != "Custom")
    end = c.date_input("Through", today, disabled=period != "Custom")
    params = {"start": start.isoformat(), "end": end.isoformat()}
    if category:
        params["category"] = category
    else:
        selected = st.selectbox("Category", ["All", "student", "teacher", "staff", "other"])
        if selected != "All":
            params["category"] = selected
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
        key=f"history_department_{category}",
    )
    classes = {None: "All classes", **{e["id"]: e["name"] for e in catalog if e["kind"] == "class"}}
    class_id = b.selectbox(
        "Class / program", list(classes), format_func=classes.get, key=f"history_class_{category}"
    )
    section = c.text_input("Section")
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
    )
    if selected_person:
        params["person_id"] = selected_person
    rows = request("GET", "/attendance", params=params)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    if rows:
        counted = [r for r in rows if r["status"] in {"present", "late", "absent"}]
        if counted:
            rate = 100 * sum(r["status"] in {"present", "late"} for r in counted) / len(counted)
            st.metric("Verified attendance rate", f"{rate:.1f}%")
        st.caption(
            "Rate = (present + late) / (present + late + finalized absent). Pending, leave, excused, holidays and unfinalized missing records are excluded."
        )
        trends(rows)
    if can("export") and (export or rows):
        kind = st.selectbox("Export format", ["csv", "xlsx", "pdf"])
        if st.button("Prepare report"):
            content = request("GET", "/reports/export", params={**params, "kind": kind})
            st.download_button(
                "Download report", content, file_name=f"attendance-{start}-{end}.{kind}"
            )
