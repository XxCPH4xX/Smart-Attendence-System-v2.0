import streamlit as st


def control_key(section, name):
    return f"{section}:{st.session_state.get(f'reset_{section}', 0)}:{name}"


def reset_section(section, clear_keys):
    st.session_state[f"reset_{section}"] = st.session_state.get(f"reset_{section}", 0) + 1
    for key in clear_keys:
        st.session_state.pop(key, None)


def reset_button(section, *, label="Reset", clear_keys=(), disabled=False):
    st.button(
        label,
        key=f"reset_button_{section}",
        help="Clear unsaved entries and filters. Saved data stays unchanged.",
        on_click=reset_section,
        args=(section, clear_keys),
        disabled=disabled,
    )


def delete_selected_person(person_id, context):
    from frontend.client import APIError, request

    try:
        request("DELETE", f"/people/{person_id}", json={"reason": "Deleted from " + context})
    except APIError as error:
        st.session_state.notice_error = str(error)
    else:
        st.session_state.notice = "Person deleted from attendance. Past records have been kept."
