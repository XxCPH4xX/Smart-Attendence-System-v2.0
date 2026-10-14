from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from frontend.client import can, request
from frontend.design import STATUS_COLORS, badge, empty, metric
from frontend.navigation import open_page, option_buttons
from frontend.registration import begin_registration


def chart_style(figure, height=275):
    figure.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=0, r=0, t=15, b=5),
        font=dict(family="sans-serif", color="#7c879f", size=11),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.15, x=0),
        xaxis_title=None,
        yaxis_title=None,
    )
    figure.update_yaxes(gridcolor="#eef1f6", rangemode="tozero")
    return figure


def render():
    data = request("GET", "/dashboard", params={"days": 90})
    quick = st.columns([1.3, 1, 1])
    with (
        quick[0],
        st.popover("Register a person", icon=":material/person_add:", disabled=not can("people")),
    ):
        for category in ("student", "teacher", "staff", "other"):
            st.button(
                "Register " + category,
                on_click=begin_registration,
                args=(category,),
                use_container_width=True,
            )
    quick[1].button(
        "Start recognition",
        icon=":material/videocam:",
        disabled=not can("camera"),
        on_click=open_page,
        args=("Live Recognition",),
    )
    quick[2].button(
        "Generate report",
        icon=":material/download:",
        disabled=not can("export"),
        on_click=open_page,
        args=("Reports & Analytics", "Export center"),
    )
    for column, category, page in zip(
        st.columns(3),
        ("student", "teacher", "staff"),
        ("Students", "Teachers", "Staff"),
        strict=True,
    ):
        with column:
            metric(
                "Total " + page.lower(),
                data["people"].get(category, 0),
                "Active registered profiles",
                destination=page,
                section="Directory",
            )
    for column, label, status, context in zip(
        st.columns(4),
        ("Present today", "Absent today", "Late today", "Pending reviews"),
        ("present", "absent", "late", "pending_verification"),
        (
            "Unique people · on time",
            "Recorded absences only",
            "Unique people · late",
            "Check-ins awaiting review",
        ),
        strict=True,
    ):
        with column:
            metric(
                label,
                data["pending_reviews"]
                if status == "pending_verification"
                else data["today"][status],
                context,
                destination="Attendance Operations"
                if status == "pending_verification"
                else "Reports & Analytics",
                section="Pending reviews"
                if status == "pending_verification"
                else "Attendance history",
                filters={"status": status},
            )
    st.caption(
        "People are counted once per day. Late takes precedence over on-time attendance; absence is shown only after a roster is finalized. Other registered roles: "
        + str(data["people"].get("other", 0))
        + "."
    )
    main, side = st.columns([2, 1])
    with main, st.container(border=True, key="card_overview_trend"):
        st.subheader("Attendance overview")
        interval = option_buttons("", ["Daily", "Weekly", "Monthly"], "overview_interval")
        frame = pd.DataFrame(data["trend"])
        frame["date"] = pd.to_datetime(frame["date"])
        if interval == "Daily":
            frame = frame.tail(14)
        else:
            frame = (
                frame.set_index("date")
                .resample("W-MON" if interval == "Weekly" else "MS")
                .sum()
                .reset_index()
            )
        melted = frame.melt(
            id_vars=["date"],
            value_vars=["present", "late", "absent"],
            var_name="Status",
            value_name="People",
        )
        figure = px.area(
            melted, x="date", y="People", color="Status", color_discrete_map=STATUS_COLORS
        )
        st.plotly_chart(
            chart_style(figure), use_container_width=True, config={"displayModeBar": False}
        )
    with side, st.container(border=True, key="card_overview_categories"):
        st.subheader("Today by category")
        categories = data["categories"]
        if categories:
            frame = pd.DataFrame(
                [
                    {
                        "Category": entry["category"].title(),
                        "Checked in": entry.get("present", 0) + entry.get("late", 0),
                    }
                    for entry in categories
                ]
            )
            if frame["Checked in"].sum():
                figure = px.pie(
                    frame,
                    names="Category",
                    values="Checked in",
                    hole=0.72,
                    color_discrete_sequence=["#5063dc", "#9da9f0", "#73c7b0", "#bfc9dd"],
                )
                st.plotly_chart(
                    chart_style(figure), use_container_width=True, config={"displayModeBar": False}
                )
            else:
                empty("No check-ins today", "Recognized or manually recorded arrivals appear here.")
        else:
            empty("A fresh attendance day", "Start the station when people are ready to check in.")
    main, side = st.columns([2, 1])
    with main, st.container(border=True, key="card_overview_recent"):
        a, b = st.columns([3, 1])
        a.subheader("Recent attendance")
        b.button(
            "View all",
            type="tertiary",
            on_click=open_page,
            args=("Reports & Analytics", "Attendance history"),
        )
        if data["recent"]:
            st.dataframe(
                [
                    {
                        "Name": row["full_name"],
                        "ID": row["institutional_id"],
                        "Category": row["person_type"],
                        "Status": row["status"].replace("_", " ").title(),
                        "Arrival": datetime.fromisoformat(row["check_in"]).strftime("%I:%M %p")
                        if row["check_in"]
                        else "—",
                    }
                    for row in data["recent"]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            empty("No arrivals recorded", "New check-ins appear here as attendance is saved.")
    with side, st.container(border=True, key="card_overview_attention"):
        st.subheader("Needs attention")
        badge(
            str(data["pending_reviews"]) + " pending attendance reviews",
            "warn" if data["pending_reviews"] else "good",
        )
        if can("correct"):
            st.button(
                "Review check-ins",
                type="tertiary",
                on_click=open_page,
                args=("Attendance Operations", "Pending reviews"),
            )
        badge(
            str(data["awaiting_enrollment"]) + " awaiting face enrollment",
            "warn" if data["awaiting_enrollment"] else "good",
        )
        if can("enroll"):
            st.button(
                "Manage enrollments",
                type="tertiary",
                on_click=open_page,
                args=("Enrollment", "Enrollment management"),
            )
        status = request("GET", "/vision/status")
        badge(
            "Recognition models ready" if status["models_prepared"] else "Model setup required",
            "good" if status["models_prepared"] else "warn",
        )
    with st.container(border=True, key="card_overview_sessions"):
        st.subheader("Active & upcoming sessions")
        if data["sessions"]:
            st.dataframe(
                [
                    {
                        "Session": session["name"],
                        "Category": "All enrolled people"
                        if session["station"]
                        else session["category"].title(),
                        "Starts": session["starts_at"],
                        "Ends": session["ends_at"],
                    }
                    for session in data["sessions"][:6]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption(
                "No scheduled sessions are active or upcoming. The shared daily station opens when recognition starts."
            )
        st.button(
            "Attendance operations",
            type="tertiary",
            on_click=open_page,
            args=("Attendance Operations", "Active sessions"),
        )
    with st.expander("Late arrivals & department trends"):
        left, right = st.columns(2)
        trend = pd.DataFrame(data["trend"]).tail(30)
        left.plotly_chart(
            chart_style(
                px.bar(
                    trend,
                    x="date",
                    y="late",
                    title="Late arrivals · last 30 days",
                    color_discrete_sequence=["#d2a25e"],
                )
            ),
            use_container_width=True,
        )
        departments = data["departments"]
        if departments:
            frame = pd.DataFrame(
                [
                    {
                        "Department": item["department"],
                        "Checked in": item.get("present", 0) + item.get("late", 0),
                    }
                    for item in departments
                ]
            )
            right.plotly_chart(
                chart_style(
                    px.bar(
                        frame,
                        x="Checked in",
                        y="Department",
                        orientation="h",
                        color_discrete_sequence=["#5063dc"],
                    )
                ),
                use_container_width=True,
            )
        else:
            right.caption("Department totals appear after attendance is recorded.")
    if can("audit"):
        with st.expander("Recent administrative changes"):
            if data["administrative_activity"]:
                st.dataframe(
                    data["administrative_activity"], hide_index=True, use_container_width=True
                )
            else:
                st.caption("No administrative changes recorded.")
