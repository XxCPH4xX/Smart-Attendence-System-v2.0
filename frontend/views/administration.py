import streamlit as st

from frontend.client import can, clear_session, request
from frontend.controls import control_key, reset_button
from frontend.design import confirmation


def users():
    reset_button("users", label="Reset account form")
    accounts = request("GET", "/users")
    st.dataframe(
        [
            {
                "Username": u["username"],
                "Role": u["role"],
                "Sign-in access": "Allowed" if u["active"] else "Removed",
            }
            for u in accounts
        ],
        hide_index=True,
        use_container_width=True,
    )
    with st.form(control_key("users", "new_user")):
        username = st.text_input("New username")
        password = st.text_input("Initial password (at least 12 characters)", type="password")
        role = st.selectbox("Role", ["viewer", "teacher", "staff_operator", "admin", "super_admin"])
        if st.form_submit_button("Create account"):
            request(
                "POST", "/users", json={"username": username, "password": password, "role": role}
            )
            st.rerun()
    selected = st.selectbox(
        "Manage account",
        accounts,
        format_func=lambda u: u["username"],
        key=control_key("users", "selected"),
    )
    st.caption(
        "Removing login access signs this account out and prevents future sign-ins. Past changes remain in the change history."
    )
    if st.button("Remove login access" if selected["active"] else "Restore login access"):
        confirmation(
            "Change login access?",
            "Removing access ends active sessions for this account.",
            request,
            args=("PATCH", f"/users/{selected['id']}"),
            kwargs={"params": {"active": not selected["active"]}},
        )
    st.caption(
        "Password recovery requires local administrator access: attendance reset-password. Changing or resetting a password expires every session for that account."
    )


def account():
    reset_button("account", label="Reset password form")
    with st.form(control_key("account", "password")):
        current = st.text_input("Current password", type="password")
        new = st.text_input("New password (at least 12 characters)", type="password")
        repeat = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change password and sign out"):
            if new != repeat:
                st.error("Passwords do not match")
            else:
                request(
                    "POST",
                    "/auth/password",
                    json={"current_password": current, "new_password": new},
                )
                clear_session()
                st.rerun()


def audit():
    reset_button("audit", label="Reset filters")
    page = st.number_input(
        "Audit page", min_value=1, value=1, step=1, key=control_key("audit", "page")
    )
    rows = request("GET", "/audit", params={"offset": (page - 1) * 100, "limit": 100})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if rows:
        entry = st.selectbox(
            "Inspect change",
            rows,
            format_func=lambda r: f"#{r['id']} · {r['action']} · {r['created_at']}",
            key=control_key("audit", "entry"),
        )
        st.json(entry)


def settings(system=False):
    scope = "system_policy" if system else "recognition_settings"
    reset_button(scope, label="Reset unsaved changes")
    config = request("GET", "/settings")
    policy = dict(config["policy"])
    st.caption(f"{config['institution']} · {config['timezone']} · {config['device'].upper()}")
    if system:
        st.caption(
            "Retention changes apply to future cleanup. Existing templates keep their original expiry date."
        )
        with st.form(control_key(scope, "form")):
            policy["template_retention_days"] = st.number_input(
                "Template retention (days, for new enrollments)",
                min_value=1,
                max_value=3650,
                value=policy["template_retention_days"],
            )
            policy["attendance_retention_days"] = st.number_input(
                "Attendance retention (days)",
                min_value=30,
                max_value=3650,
                value=policy["attendance_retention_days"],
            )
            if st.form_submit_button("Save retention policy"):
                request("PUT", "/settings", json=policy)
                st.success("System policy saved")
        st.code(
            "attendance backup data/backups/attendance.db\nattendance purge-expired\nattendance purge-expired --apply",
            language="bash",
        )
        st.caption(
            "Purge starts as a dry run. Store backups securely and retain the encryption key separately. Audit and authorization records need an institution-approved retention policy."
        )
    else:
        st.warning(
            "Similarity scores are not probabilities. The default threshold is provisional until evaluated on authorized local data. Daily station marking and staff review can be configured under Camera configuration. Face matching does not prove liveness."
        )
        with st.form(control_key(scope, "form")):
            a, b = st.columns(2)
            with a:
                policy["similarity_threshold"] = st.slider(
                    "Cosine acceptance threshold", 0.5, 0.99, policy["similarity_threshold"], 0.01
                )
                policy["ambiguity_margin"] = st.slider(
                    "Minimum competing-identity margin", 0.02, 0.5, policy["ambiguity_margin"], 0.01
                )
                policy["stable_observations"] = st.number_input(
                    "Consistent observations", 3, 10, policy["stable_observations"]
                )
                policy["stable_seconds"] = st.number_input(
                    "Minimum observation duration (seconds)",
                    1.0,
                    10.0,
                    policy["stable_seconds"],
                    0.5,
                )
            with b:
                policy["processing_width"] = st.number_input(
                    "Processing width (pixels)", 320, 1280, policy["processing_width"], 80
                )
                policy["processing_interval"] = st.number_input(
                    "Inference interval (seconds)", 0.2, 5.0, policy["processing_interval"], 0.1
                )
                policy["min_face_pixels"] = st.number_input(
                    "Minimum face size (pixels)", 40, 300, policy["min_face_pixels"]
                )
                policy["min_blur_variance"] = st.number_input(
                    "Minimum sharpness variance", 10.0, 500.0, policy["min_blur_variance"]
                )
            if st.form_submit_button("Save recognition policy"):
                request("PUT", "/settings", json=policy)
                st.success("Policy saved. Restart an active camera to apply timing changes.")


def evaluation():
    status = request("GET", "/vision/status")
    st.json(status)
    st.info(
        "No institutional recognition accuracy is claimed. Evaluation requires authorized images from distinct capture sessions, including people absent from the enrollment set."
    )
    st.markdown(
        "Open `notebooks/recognition_evaluation.ipynb` to extract embeddings, compare cosine, KNN and approximate search, calibrate thresholds on validation sessions, and measure the locked test split."
    )
    st.code("uv run jupyter notebook notebooks/recognition_evaluation.ipynb", language="bash")
    st.write(
        "The dashboard uses cosine matching as a provisional baseline. ANN and KNN are experimental comparisons until your evaluation supports changing the operational method. StandardScaler and an MLP are not enabled without evidence that they improve open-set decisions."
    )


def institution():
    from zoneinfo import available_timezones

    config = request("GET", "/settings")
    reset_button("institution", label="Reset unsaved changes")
    with st.form(control_key("institution", "form")):
        name = st.text_input("Institution name", config["institution"], max_chars=120)
        zones = sorted(available_timezones())
        timezone = st.selectbox(
            "Institution timezone", zones, index=zones.index(config["timezone"])
        )
        st.caption(
            "New sessions use this timezone. Existing sessions keep their original timezone and timestamps."
        )
        if st.form_submit_button("Save institution", type="primary"):
            request("PUT", "/institution", json={"name": name, "timezone": timezone})
            st.session_state.notice = "Institution settings saved."
            st.rerun()


def roles():
    from backend.auth import PERMISSIONS

    st.caption(
        "Permissions are enforced by the API. Teacher access covers institution-wide reports; it is not limited to an assigned class."
    )
    labels = {
        "read": "View records",
        "people": "Manage profiles",
        "enroll": "Enroll faces",
        "camera": "Live camera",
        "correct": "Correct attendance",
        "schedule": "Schedules & leave",
        "export": "Export reports",
        "delete_attendance": "Delete attendance",
        "privacy": "Delete people & biometrics",
        "settings": "System settings",
        "users": "Login accounts",
        "audit": "Audit history",
    }
    st.dataframe(
        [
            {
                "Permission": label,
                **{
                    role.replace("_", " ").title(): "✓" if permission in permissions else "—"
                    for role, permissions in PERMISSIONS.items()
                },
            }
            for permission, label in labels.items()
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_admin():
    from frontend.navigation import section_tabs

    sections = ["My account", "Roles & permissions"]
    if can("users"):
        sections.insert(0, "User accounts")
    if can("settings"):
        sections.append("Institution")
    if can("audit"):
        sections.append("Audit logs")
    selected = section_tabs(sections, "Administration")
    {
        "My account": account,
        "Roles & permissions": roles,
        "User accounts": users,
        "Institution": institution,
        "Audit logs": audit,
    }[selected]()


def render_system():
    from frontend.navigation import section_tabs
    from frontend.views.live import station_settings

    sections = ["Recognition status"]
    if can("settings"):
        sections = [
            "Camera configuration",
            "Recognition settings",
            "Attendance policies",
            "Privacy & retention",
            *sections,
        ]
    selected = section_tabs(sections, "System Settings")
    if selected == "Recognition status":
        evaluation()
    elif selected == "Camera configuration":
        station_settings(request("GET", "/settings")["policy"])
    elif selected == "Recognition settings":
        settings()
    elif selected == "Attendance policies":
        config = request("GET", "/settings")
        policy = config["policy"]
        reset_button("attendance_policy", label="Reset unsaved changes")
        with st.form(control_key("attendance_policy", "form")):
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            policy["working_days"] = st.multiselect(
                "Working days",
                list(range(7)),
                default=policy["working_days"],
                format_func=lambda value: days[value],
            )
            policy["station_auto_mark"] = st.toggle(
                "Mark stable face matches automatically", policy["station_auto_mark"]
            )
            st.caption(
                "Disable automatic marking to require staff review at the daily station. Scheduled sessions always require review. Grace periods and checkout rules are set per scheduled session."
            )
            if st.form_submit_button("Save attendance policy", type="primary"):
                request("PUT", "/settings", json=policy)
                st.success("Attendance policy saved.")
    else:
        settings(True)
