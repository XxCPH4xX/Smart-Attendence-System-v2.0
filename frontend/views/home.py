import streamlit as st

from frontend.client import can, request
from frontend.navigation import navigate


def render():
    summary = request("GET", "/overview")
    st.caption(f"{summary['institution']} · {summary['date']}")
    st.subheader("What would you like to do?")
    columns = st.columns(3)
    actions = [
        ("Take attendance", "Start one camera for everyone.", "camera", "Take attendance"),
        ("Add a person", "Save a name, ID and face samples.", "people", "People"),
        ("View records", "Review attendance and download reports.", "read", "Records"),
    ]
    for column, (label, description, permission, page) in zip(columns, actions, strict=True):
        with column, st.container(border=True):
            st.write(f"**{label}**")
            st.caption(description)
            st.button(
                label,
                key=f"home_{page}",
                use_container_width=True,
                disabled=not can(permission),
                on_click=navigate,
                args=(page, None, "Add person" if page == "People" else None),
            )

    if can("enroll"):
        results = request("GET", "/people", params={"q": "DEMO-001", "limit": 10})
        demo = next((p for p in results["items"] if p["institutional_id"] == "DEMO-001"), None)
        with st.container(border=True):
            st.subheader("Try face recognition")
            if not demo:
                st.write("Create a test profile, add your face, then try the camera.")
                if st.button("Create test profile", type="primary"):
                    request("POST", "/demo/person")
                    st.rerun()
            else:
                st.write("**Demo Student** · DEMO-001 · Test profile")
                steps = [
                    "✓ Test profile created",
                    "✓ Face added" if demo["enrolled"] else "2. Add your face",
                    "3. Try the camera",
                ]
                st.caption("  →  ".join(steps))
                if not demo["active"]:
                    st.info("This test profile is inactive. You can reactivate it in People.")
                elif not demo["enrolled"]:
                    st.write("Next: give permission and take three clear photos of your own face.")
                    st.caption(
                        "Already enrolled under your name? Use Take attendance with that profile. Each face can belong to only one person."
                    )
                    st.button(
                        "Add my face",
                        type="primary",
                        on_click=navigate,
                        args=("People", demo["id"], "Enroll a face"),
                    )
                else:
                    st.success("Your test profile is ready for the camera.")
                    st.button(
                        "Try the camera",
                        type="primary",
                        disabled=not can("camera"),
                        on_click=navigate,
                        args=("Take attendance", demo["id"]),
                    )
                st.caption(
                    "Use your current sign-in. This is a test attendance profile, not another login. Test attendance is labelled with DEMO-001 in reports."
                )
    st.subheader("Today at a glance")
    totals = summary["attendance"]
    a, b, c = st.columns(3)
    a.metric("People registered", sum(summary["people"].values()))
    b.metric("Checked in", totals.get("present", 0) + totals.get("late", 0))
    c.metric("Waiting for review", totals.get("pending_verification", 0))
    st.caption(
        "The daily station marks enrolled people automatically. Scheduled sessions can require review."
    )
