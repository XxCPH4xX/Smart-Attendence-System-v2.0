from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from backend.config import get_settings
from backend.db import utcnow
from frontend.attendance_actions import confirm_delete, undo_button
from frontend.client import APIError, can, request
from frontend.controls import control_key, reset_button
from frontend.design import empty, person_identity
from frontend.navigation import open_page
from vision.camera import RemoteProcessor


def station_settings(policy):
    with st.expander("Camera & station configuration", expanded=True):
        st.caption(
            "Choose a camera using the camera selector in the live preview. Stop the station before changing its settings."
        )
        if can("settings"):
            reset_button(
                "station_settings",
                label="Reset unsaved settings",
                disabled=bool(st.session_state.get("stream_id")),
            )
            with st.form(control_key("station_settings", "form")):
                name = st.text_input("Station name", policy["station_name"], max_chars=100)
                mode = st.selectbox(
                    "When a person is recognized",
                    ["Mark attendance automatically", "Send check-in for staff review"],
                    index=0 if policy["station_auto_mark"] else 1,
                )
                interval = st.slider(
                    "Check for faces every (seconds)",
                    0.2,
                    5.0,
                    float(policy["processing_interval"]),
                    0.1,
                )
                st.caption(
                    "A shorter interval responds faster and uses more CPU. Face matches do not prove liveness; photos or screens may fool the camera."
                )
                if st.form_submit_button(
                    "Save station settings", disabled=bool(st.session_state.get("stream_id"))
                ):
                    request(
                        "PUT",
                        "/settings",
                        json={
                            **policy,
                            "station_name": name,
                            "station_auto_mark": mode == "Mark attendance automatically",
                            "processing_interval": interval,
                        },
                    )
                    st.session_state.notice = "Station settings saved."
                    st.rerun()
        st.caption(
            "For matching sensitivity, image quality and resolution, open System Settings → Recognition settings."
        )


def stop_stream():
    processor = st.session_state.pop("processor", None)
    stream_id = st.session_state.pop("stream_id", None)
    st.session_state.pop("was_playing", None)
    if processor:
        processor.close()
    elif stream_id:
        request("DELETE", f"/vision/streams/{stream_id}")


def capture_activity(result, timezone):
    observed = result.get("observed_at") or utcnow().isoformat()
    timestamp = datetime.fromisoformat(observed).astimezone(ZoneInfo(timezone)).strftime("%H:%M:%S")
    current = set()
    events = st.session_state.setdefault("live_events", [])
    previous = st.session_state.get("live_event_signatures", set())
    entries = result.get("faces", [])
    if result.get("error"):
        entries = [{"name": "Camera", "feedback": result["error"], "status": "error"}]
    for face in entries:
        signature = (
            face.get("person_id"),
            face.get("status"),
            face.get("attendance_status"),
            face.get("feedback"),
        )
        current.add(signature)
        if signature not in previous:
            events.insert(
                0,
                {
                    "Time": timestamp,
                    "Person": face.get("name", "Unknown"),
                    "Event": face.get("feedback", ""),
                    "Status": (face.get("attendance_status") or face.get("status", "waiting"))
                    .replace("_", " ")
                    .title(),
                },
            )
        if face.get("person_id"):
            st.session_state.live_latest = {**face, "observed_at": observed}
    st.session_state.live_event_signatures = current
    del events[50:]


def clear_live_activity():
    for key in ("live_events", "live_event_signatures", "live_latest"):
        st.session_state.pop(key, None)


def render():
    config = request("GET", "/settings")
    policy = config["policy"]
    running = bool(st.session_state.get("stream_id"))
    st.caption(policy["station_name"])
    with st.expander("Class or shift attendance (optional)"):
        scheduled = st.toggle("Use a scheduled session", key="scheduled_camera", disabled=running)
        if scheduled:
            now = utcnow()
            sessions = {
                s["id"]: s
                for s in request("GET", "/sessions")
                if not s.get("station")
                and not s["finalized"]
                and datetime.fromisoformat(s["starts_at"])
                <= now
                <= datetime.fromisoformat(s["cutoff_at"])
            }
            if not sessions:
                st.info(
                    "No scheduled check-in window is open. Create one in Attendance Operations → Active sessions, or turn this option off to use the daily station."
                )
            selected = (
                st.selectbox(
                    "Class or shift",
                    list(sessions),
                    format_func=lambda i: sessions[i]["name"],
                    disabled=running,
                )
                if sessions
                else None
            )
        else:
            selected = None
    station = request("GET", "/station")
    session_id = selected if scheduled else (station["session"] or {}).get("id")
    day = sessions[selected]["local_date"] if scheduled and selected else station["date"]
    if can("delete_attendance"):
        st.button(
            "Reset session attendance" if scheduled else "Reset today's attendance",
            on_click=confirm_delete,
            kwargs={"params": {"start": day, "end": day, "session_id": session_id}},
            disabled=session_id is None,
            help="Clear this session's check-ins and stop its cameras. People and saved faces stay available.",
        )
        undo_button()
    if not scheduled:
        count = station["enrolled_people"]
        st.caption(
            f"{count} enrolled {'person' if count == 1 else 'people'} ready · One check-in per person each day · New day starts automatically"
        )
    review = scheduled or not policy["station_auto_mark"]
    st.caption(
        "Check-ins go to Attendance Operations → Pending reviews."
        if review
        else "Stable face matches are marked Present automatically. Unknown faces are not registered or marked."
    )
    if not running:
        if not station["enrolled_people"]:
            st.info(
                "Add face samples in Enrollment → Face enrollment. You can still open the camera to check its view."
            )
        if st.button(
            "Start attendance station", type="primary", disabled=scheduled and selected is None
        ):
            with st.spinner("Starting the camera and face recognition…"):
                result = (
                    request("POST", "/vision/streams", json={"session_id": selected})
                    if scheduled
                    else request("POST", "/station/start")
                )
            clear_live_activity()
            st.session_state.stream_id = result["stream_id"]
            st.session_state.camera_session_id = selected
            st.rerun()
        preview, details = st.columns([2.7, 1.1])
        with preview, st.container(border=True):
            st.html(
                '<div style="height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#1b2540;border-radius:10px;color:#dbe3f7"><span style="font-size:40px">◉</span><strong style="margin:12px 0">Camera is off</strong><span style="font-size:13px;color:#9aa8c6">Start the station to begin live recognition</span></div>'
            )
        with details, st.container(border=True):
            st.subheader("Latest recognition")
            empty(
                "Waiting for the camera",
                "Recognized people and their attendance status appear here.",
            )
        st.caption(
            "Allow camera access once. Keep this page open and your computer awake while people check in. Video is not saved."
        )
    else:
        stop, refresh, settings = st.columns([1, 1, 2])
        if stop.button("Stop attendance station", icon=":material/stop_circle:"):
            stop_stream()
            st.rerun()
        if refresh.button("Refresh camera", icon=":material/refresh:"):
            stop_stream()
            result = (
                request("POST", "/vision/streams", json={"session_id": selected})
                if scheduled
                else request("POST", "/station/start")
            )
            st.session_state.stream_id = result["stream_id"]
            st.rerun()
        settings.caption("Select your camera in the live preview controls.")
        camera, activity = st.columns([2.7, 1.1])
        with camera:
            stream_id = st.session_state.stream_id
            token = st.session_state.token

            def factory():
                return RemoteProcessor(
                    get_settings().api_url,
                    token,
                    stream_id,
                    policy["processing_interval"],
                    policy["processing_width"],
                    station=not scheduled,
                )

            context = webrtc_streamer(
                key=f"camera-{stream_id}",
                desired_playing_state=True,
                mode=WebRtcMode.SENDRECV,
                rtc_configuration={"iceServers": []},
                media_stream_constraints={
                    "video": {
                        "width": {"ideal": policy["processing_width"]},
                        "height": {"ideal": 480},
                    },
                    "audio": False,
                },
                video_processor_factory=factory,
                async_processing=False,
            )
            if context.video_processor:
                st.session_state.processor = context.video_processor
            if not context.state.playing and st.session_state.get("was_playing"):
                stop_stream()
                st.session_state.notice = "Camera disconnected. Start the station to reconnect."
                st.rerun()
            st.session_state.was_playing = context.state.playing
        with activity:

            @st.fragment(run_every=1)
            def feedback():
                processor = st.session_state.get("processor")
                if not processor:
                    st.info("Connecting camera… Allow access when your browser asks.")
                    return
                result = processor.snapshot()
                capture_activity(result, config["timezone"])
                if result.get("stopped"):
                    stop_stream()
                    st.session_state.notice = result["error"]
                    st.rerun()
                if result.get("error"):
                    st.error(result["error"])
                    return
                st.subheader("Latest recognition")
                st.metric("Processing time", f"{result.get('latency_ms', 0):.0f} ms")
                latest = st.session_state.get("live_latest")
                faces = [latest] if latest else result.get("faces", [])[:1]
                if not faces:
                    st.success("Station ready")
                    st.write("Waiting for someone to approach…")
                for face in faces:
                    person_identity(
                        {
                            "full_name": face["name"],
                            "institutional_id": face.get("institutional_id", "Unregistered"),
                        }
                    )
                    st.caption(face["label"])
                    st.caption(
                        "Session: "
                        + (
                            sessions[selected]["name"]
                            if scheduled and selected
                            else (station["session"] or {}).get("name", policy["station_name"])
                        )
                    )
                    event_time = face.get("check_in") or face.get("observed_at")
                    if event_time:
                        st.caption(
                            "Last event: "
                            + datetime.fromisoformat(event_time)
                            .astimezone(ZoneInfo(config["timezone"]))
                            .strftime("%d %b · %H:%M:%S")
                        )
                    if face.get("person_id") and can("people"):
                        photo_key = f"live_photo_{face['person_id']}"
                        if photo_key not in st.session_state:
                            try:
                                st.session_state[photo_key] = request(
                                    "GET", f"/people/{face['person_id']}/photo"
                                )
                            except APIError:
                                st.session_state[photo_key] = None
                        if st.session_state[photo_key]:
                            st.image(st.session_state[photo_key], width=96)
                    if face.get("attendance_status") == "present":
                        st.success(face.get("feedback", "Attendance marked"))
                    else:
                        st.info(face.get("feedback", "Look toward the camera for a moment…"))

            feedback()
    if can("settings"):
        st.button(
            "Camera configuration",
            type="tertiary",
            icon=":material/tune:",
            on_click=open_page,
            args=("System Settings", "Camera configuration"),
        )

    @st.fragment(run_every=3)
    def recent():
        current = request("GET", "/station")
        session_id = selected if scheduled else (current["session"] or {}).get("id")
        day = sessions[selected]["local_date"] if scheduled and selected else current["date"]
        rows = (
            request(
                "GET", "/attendance", params={"start": day, "end": day, "session_id": session_id}
            )
            if session_id
            else []
        )
        a, b = st.columns(2)
        a.metric("Checked in today", sum(row["status"] in {"present", "late"} for row in rows))
        b.metric("Waiting for review", sum(row["status"] == "pending_verification" for row in rows))
        st.subheader("Recent arrivals")
        if not rows:
            st.caption("Recognized people will appear here automatically.")
        else:
            st.dataframe(
                [
                    {
                        "Name": row["full_name"],
                        "ID": row["institutional_id"],
                        "Type": row["person_type"],
                        "Status": row["status"].replace("_", " ").title(),
                        "Check-in": datetime.fromisoformat(row["check_in"]).strftime("%I:%M:%S %p")
                        if row["check_in"]
                        else "—",
                    }
                    for row in sorted(rows, key=lambda row: row["check_in"] or "", reverse=True)
                ],
                hide_index=True,
                use_container_width=True,
            )

        with st.expander("Recognition activity", expanded=bool(st.session_state.get("stream_id"))):
            events = st.session_state.get("live_events", [])
            if events:
                st.dataframe(events, hide_index=True, use_container_width=True)
                st.caption(
                    "Last 50 recognition changes in this browser session. Attendance records are saved separately."
                )
            else:
                st.caption(
                    "Recognition changes, errors and timestamps appear while the camera is running."
                )

    recent()
