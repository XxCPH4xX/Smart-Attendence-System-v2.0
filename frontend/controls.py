import hashlib

import streamlit as st

from frontend.client import person_label


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


def clear_table_selection(section):
    key = control_key(section, "table_version")
    st.session_state[key] = st.session_state.get(key, 0) + 1


def people_table(rows, row_ids, people, section):
    identity = hashlib.sha256(str(row_ids).encode()).hexdigest()[:12]
    version = st.session_state.get(control_key(section, "table_version"), 0)
    table_key = control_key(section, f"table_{identity}_{version}")
    picker_key = control_key(section, "person")
    selection = st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )
    if not people:
        return None
    selected_rows = selection.selection.rows
    last_key = control_key(section, "last_row")
    if selected_rows and st.session_state.get(last_key) != (table_key, selected_rows[0]):
        st.session_state[picker_key] = row_ids[selected_rows[0]]
        st.session_state[last_key] = (table_key, selected_rows[0])
    elif not selected_rows and st.session_state.get(last_key, (None,))[0] == table_key:
        st.session_state[picker_key] = None
        st.session_state.pop(last_key, None)
    if st.session_state.get(picker_key) not in people:
        st.session_state[picker_key] = None
    st.caption("Select a row or choose a person below to see their actions.")
    return st.selectbox(
        "Selected person",
        list(people),
        index=None,
        placeholder="Choose a person",
        format_func=lambda i: person_label(people[i]),
        key=picker_key,
        on_change=clear_table_selection,
        args=(section,),
    )


def delete_selected_person(person_id, context):
    from frontend.client import APIError, request

    try:
        request("DELETE", f"/people/{person_id}", json={"reason": "Deleted from " + context})
    except APIError as error:
        st.session_state.notice_error = str(error)
    else:
        st.session_state.notice = "Person deleted from attendance. Past records have been kept."


def delete_person_button(person, context):
    st.caption(
        f"Delete {person['full_name']} ({person['institutional_id']}) from attendance. "
        "Saved face data is erased; past attendance records are kept."
    )
    st.button(
        "Delete person",
        key=f"delete_{context}_{person['id']}",
        on_click=delete_selected_person,
        args=(person["id"], context),
    )
