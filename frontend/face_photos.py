import hashlib

import streamlit as st

from frontend.client import request
from frontend.controls import control_key
from frontend.navigation import option_buttons


def reset_capture(person_id):
    key = f"capture_generation_{person_id}"
    st.session_state[key] = st.session_state.get(key, 0) + 1


def remove_photo(person_id, index):
    st.session_state[f"samples_{person_id}"].pop(index)
    target = st.session_state.get(f"retake_{person_id}")
    if target == index:
        st.session_state.pop(f"retake_{person_id}", None)
        reset_capture(person_id)
    elif target is not None and target > index:
        st.session_state[f"retake_{person_id}"] = target - 1


def retake_photo(person_id, index):
    st.session_state[f"retake_{person_id}"] = index
    st.session_state[f"photo_source_{person_id}"] = "Use webcam"
    reset_capture(person_id)


def cancel_retake(person_id):
    st.session_state.pop(f"retake_{person_id}", None)
    reset_capture(person_id)


def clear_photos(person_id):
    st.session_state[f"samples_{person_id}"] = []
    cancel_retake(person_id)


def add_uploads(person_id, widget_key):
    saved = st.session_state[f"samples_{person_id}"]
    seen = {hashlib.sha256(content).digest() for _, content in saved}
    additions = []
    for upload in st.session_state.get(widget_key, []):
        content = upload.getvalue()
        digest = hashlib.sha256(content).digest()
        if digest not in seen:
            additions.append((upload.name, content))
            seen.add(digest)
    if len(saved) + len(additions) > 12:
        st.session_state[f"photo_notice_{person_id}"] = (
            "Keep up to 12 photos. Remove a photo before adding more."
        )
    elif not additions:
        st.session_state[f"photo_notice_{person_id}"] = (
            "These photos are already in your selection."
        )
    else:
        saved.extend(additions)
    reset_capture(person_id)


def photo_editor(person_id):
    scope = f"enrollment_{person_id}"
    saved = st.session_state.setdefault(f"samples_{person_id}", [])
    target = st.session_state.get(f"retake_{person_id}")
    generation = st.session_state.get(f"capture_generation_{person_id}", 0)
    source = option_buttons(
        "Photo source", ["Use webcam", "Upload photos"], key=f"photo_source_{person_id}"
    )
    notice = st.session_state.pop(f"photo_notice_{person_id}", None)
    if notice:
        st.warning(notice)
    st.progress(min(len(saved) / 3, 1), text=f"{len(saved)} photos ready · 3 required")
    if source == "Upload photos":
        widget_key = control_key(scope, f"uploads_{generation}")
        st.file_uploader(
            "Add photos",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=widget_key,
            on_change=add_uploads,
            args=(person_id, widget_key),
        )
    else:
        st.html("""
            <style>
            .st-key-face_capture { max-width: 360px; }
            [data-testid="stCameraInput"] { max-width: 360px; }
            [data-testid="stCameraInput"] video,
            [data-testid="stCameraInput"] img {
                max-height: 260px;
                object-fit: contain;
            }
            </style>
        """)
        with st.container(key="face_capture"):
            if target is not None:
                st.caption(
                    f"Retaking photo {target + 1}. Your previous photo stays until you use the replacement."
                )
                st.button("Cancel retake", on_click=cancel_retake, args=(person_id,))
            elif len(saved) < 3:
                st.caption(
                    [
                        "Photo 1: Look straight ahead",
                        "Photo 2: Turn slightly left",
                        "Photo 3: Turn slightly right",
                    ][len(saved)]
                )
            capture = st.camera_input(
                "Take a photo",
                key=control_key(scope, f"capture_{person_id}_{generation}"),
                disabled=len(saved) >= 12 and target is None,
                label_visibility="collapsed",
            )
            if capture:
                use, retake = st.columns(2)
                keep = use.button("Use photo", type="primary", use_container_width=True)
                retake.button(
                    "Retake", on_click=reset_capture, args=(person_id,), use_container_width=True
                )
                if keep:
                    content = capture.getvalue()
                    if target is None and len(saved) >= 12:
                        st.warning("Keep up to 12 photos. Remove a photo before adding more.")
                    elif any(content == value for i, (_, value) in enumerate(saved) if i != target):
                        st.warning("This photo is already saved. Take a new one.")
                    else:
                        result = request(
                            "POST",
                            "/vision/quality",
                            files={"file": ("capture.jpg", content, "image/jpeg")},
                        )
                        if result["acceptable"]:
                            photo = (f"capture-{generation}.jpg", content)
                            if target is None:
                                saved.append(photo)
                            else:
                                saved[target] = photo
                            cancel_retake(person_id)
                            st.rerun()
                        else:
                            st.warning(
                                "; ".join(result["feedback"])
                                or "No face found. Face the camera in good light."
                            )
    if saved:
        st.caption("Your selected photos")
        for start in range(0, len(saved), 3):
            columns = st.columns(3)
            for index in range(start, min(start + 3, len(saved))):
                with columns[index - start]:
                    st.image(saved[index][1], width=100)
                    st.caption(f"Photo {index + 1}")
                    st.button(
                        "Retake",
                        key=f"retake_photo_{person_id}_{index}",
                        on_click=retake_photo,
                        args=(person_id, index),
                        use_container_width=True,
                    )
                    st.button(
                        "Remove",
                        key=f"remove_photo_{person_id}_{index}",
                        on_click=remove_photo,
                        args=(person_id, index),
                        use_container_width=True,
                    )
        st.button("Clear selected photos", on_click=clear_photos, args=(person_id,))
    return saved
