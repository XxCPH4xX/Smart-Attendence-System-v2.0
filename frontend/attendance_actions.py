import streamlit as st

from frontend.client import APIError, request


def delete_attendance(params=None, record=None):
    from frontend.views.live import stop_stream

    try:
        if record:
            result = request(
                "DELETE",
                f"/attendance/{record['record_id']}",
                json={
                    "expected_version": record["version"],
                    "expected_updated_at": record["updated_at"],
                },
            )
        else:
            result = request("DELETE", "/attendance", params=params)
        st.session_state.last_attendance_deletion = result["deletion_id"]
        st.session_state.notice = (
            f"{result['deleted']} attendance {'record' if result['deleted'] == 1 else 'records'} cleared. "
            "People and saved faces are unchanged. Start the station again when ready."
        )
        stop_stream()
    except APIError as error:
        st.session_state.notice_error = str(error)


def restore_attendance(deletion_id):
    try:
        result = request("POST", f"/attendance-deletions/{deletion_id}/restore")
        st.session_state.notice = f"{result['restored']} attendance records restored."
        st.session_state.pop("last_attendance_deletion", None)
    except APIError as error:
        st.session_state.notice_error = str(error)


def undo_button():
    last = st.session_state.get("last_attendance_deletion")
    if last:
        st.button(
            "Undo last attendance reset or deletion", on_click=restore_attendance, args=(last,)
        )


def recovery_controls():
    undo_button()
    with st.expander("Recently deleted attendance"):
        entries = request("GET", "/attendance-deletions")
        st.caption(
            "Deleted attendance can be restored for 30 days. New check-ins will not be overwritten."
        )
        if not entries:
            st.caption("No deleted attendance to restore.")
            return
        options = {entry["id"]: entry for entry in entries}
        selected = st.selectbox(
            "Deleted group",
            list(options),
            format_func=lambda key: f"{options[key]['count']} records · {options[key]['created_at'][:16].replace('T', ' ')} UTC",
            key="deleted_attendance_group",
        )
        st.button("Restore records", on_click=restore_attendance, args=(selected,))
