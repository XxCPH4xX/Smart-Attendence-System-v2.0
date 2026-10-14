import streamlit as st

from frontend.client import can, person_label, request
from frontend.controls import control_key, reset_button
from frontend.face_photos import clear_photos, photo_editor
from frontend.navigation import open_page


def enrollment(person):
    person_id = person["id"]
    scope = f"enrollment_{person_id}"
    reset_button(
        scope,
        label="Reset enrollment form",
        clear_keys=(
            f"samples_{person_id}",
            f"replace_face_{person_id}",
            f"photo_source_{person_id}",
            f"retake_{person_id}",
            f"photo_notice_{person_id}",
        ),
    )
    st.subheader(person_label(person))
    if not person["active"]:
        st.info("Restore check-in access from the person’s directory before adding face samples.")
        return
    history = request("GET", f"/people/{person_id}/enrollments")
    consents = [
        c
        for c in history["consents"]
        if not c["revoked_at"] and (not person["is_minor"] or c["guardian"])
    ]
    replacing = st.session_state.get(f"replace_face_{person_id}", False)
    if person["enrolled"] and not replacing:
        st.success("Face enrollment is complete. This person is ready for attendance.")
        if can("camera"):
            st.button(
                "Take attendance",
                type="primary",
                on_click=open_page,
                args=("Live Recognition",),
            )
        if st.button("Replace face samples"):
            st.session_state[f"replace_face_{person_id}"] = True
            st.rerun()
    elif not consents:
        days = request("GET", "/settings")["policy"]["template_retention_days"]
        st.markdown("#### 1. Permission to use facial recognition")
        st.write(
            f"We keep an encrypted face template for up to {days} days. Enrollment photos and camera footage are not saved. You can remove the template later or use manual attendance instead."
        )
        with st.form(control_key(scope, "consent")):
            basis = st.selectbox(
                "Permission type",
                ["explicit_consent", "institutional_authorization"],
                format_func=lambda x: "Personal consent"
                if x == "explicit_consent"
                else "Institutional authorization",
            )
            guardian = (
                st.text_input("Guardian name and authorization reference")
                if person["is_minor"]
                else None
            )
            statement = st.text_area(
                "Consent or authorization note",
                value="Consent given for face matching to record attendance, with encrypted template storage and the option to revoke or use manual attendance.",
            )
            acknowledged = st.checkbox(
                "I have the person's informed permission to enroll their face."
            )
            submitted = st.form_submit_button("Agree and continue", type="primary")
        if submitted:
            if not acknowledged:
                st.error("Confirm permission before continuing.")
            elif person["is_minor"] and not guardian:
                st.error("Add the guardian's authorization before continuing.")
            else:
                request(
                    "POST",
                    f"/people/{person_id}/consent",
                    json={"basis": basis, "statement": statement, "guardian": guardian or None},
                )
                st.rerun()
    else:
        st.caption("✓ Permission recorded")
        st.markdown("#### 2. Add three clear face photos")
        st.write(
            "Take one looking straight ahead, one slightly left, and one slightly right. Keep only your face in the picture."
        )
        images = photo_editor(person_id)
        count = len(images)
        if st.button("Save face and finish", type="primary", disabled=not 3 <= count <= 12):
            with st.spinner("Checking your photos and saving the face template…"):
                request(
                    "POST",
                    f"/people/{person_id}/enroll",
                    params={"consent_id": consents[-1]["id"]},
                    files=[("files", (name, content)) for name, content in images],
                )
            clear_photos(person_id)
            st.session_state[f"replace_face_{person_id}"] = False
            st.session_state.notice = "Face saved. You can now try attendance with the camera."
            st.rerun()
    with st.expander("Enrollment history and removal"):
        st.dataframe(history["enrollments"], use_container_width=True, hide_index=True)
        if consents or person["enrolled"]:
            reason = st.text_input(
                "Reason for removing face data", key=control_key(scope, "reason")
            )
            confirmed = st.checkbox(
                "Remove the face template and profile photo, and revoke permission",
                key=control_key(scope, "confirm"),
            )
            if st.button("Remove face data", disabled=not confirmed):
                request("DELETE", f"/people/{person_id}/biometrics", json={"reason": reason})
                clear_photos(person_id)
                st.session_state.pop(f"replace_face_{person_id}", None)
                st.rerun()
