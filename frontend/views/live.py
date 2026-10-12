from datetime import datetime

import streamlit as st
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from backend.config import get_settings
from backend.db import utcnow
from frontend.client import can, request
from frontend.views.schedules import quick_session
from vision.camera import RemoteProcessor


def render():
    st.caption("Choose an attendance session, then start the camera. Staff review each check-in.")
    if st.session_state.pop("attendance_session_created", False):
        st.session_state.new_attendance_session = False
    now = utcnow()
    sessions = {
        s["id"]: s
        for s in request("GET", "/sessions")
        if not s["finalized"]
        and datetime.fromisoformat(s["starts_at"]) <= now <= datetime.fromisoformat(s["cutoff_at"])
    }
    if not sessions:
        st.info("Start a session to choose whose attendance you want to record.")
        if can("schedule"):
            quick_session()
        else:
            st.write("Ask an administrator to create a session and assign its people.")
        return
    preferred = st.session_state.get("preferred_session_id")
    selected = st.selectbox(
        "Attendance session",
        list(sessions),
        index=list(sessions).index(preferred) if preferred in sessions else 0,
        format_func=lambda i: sessions[i]["name"],
        disabled=bool(st.session_state.get("stream_id")),
    )
    if not st.session_state.get("stream_id") and can("schedule"):
        if st.toggle("Start a different session", key="new_attendance_session"):
            quick_session()
            return
    policy = request("GET", "/settings")["policy"]
    if not st.session_state.get("stream_id"):
        if st.button("Start camera", type="primary"):
            result = request("POST", "/vision/streams", json={"session_id": selected})
            st.session_state.stream_id = result["stream_id"]
            st.rerun()
        st.caption(
            "Allow camera access when your browser asks. Stay in view for a few seconds; no video is saved."
        )
        return
    if st.button("Stop camera"):
        if st.session_state.get("processor"):
            st.session_state.processor.close()
            del st.session_state.processor
        else:
            request("DELETE", f"/vision/streams/{st.session_state.stream_id}")
        del st.session_state.stream_id
        st.rerun()
    main, side = st.columns([3, 1])
    with main:
        stream_id = st.session_state.stream_id
        token = st.session_state.token

        def factory():
            return RemoteProcessor(
                get_settings().api_url,
                token,
                stream_id,
                policy["processing_interval"],
                policy["processing_width"],
            )

        context = webrtc_streamer(
            key=f"camera-{stream_id}",
            desired_playing_state=True,
            mode=WebRtcMode.SENDRECV,
            rtc_configuration={"iceServers": []},
            media_stream_constraints={
                "video": {"width": {"ideal": 640}, "height": {"ideal": 480}},
                "audio": False,
            },
            video_processor_factory=factory,
            async_processing=False,
        )
        if context.video_processor:
            st.session_state.processor = context.video_processor
        if not context.state.playing and st.session_state.get("was_playing"):
            if st.session_state.get("processor"):
                st.session_state.processor.close()
                del st.session_state.processor
            st.session_state.pop("stream_id", None)
            st.session_state.was_playing = False
            st.rerun()
        st.session_state.was_playing = context.state.playing
    with side:

        @st.fragment(run_every=1)
        def feedback():
            processor = st.session_state.get("processor")
            if not processor:
                st.info("Allow camera access in your browser to begin.")
                return
            result = processor.snapshot()
            st.metric("Last inference", f"{result.get('latency_ms', 0):.0f} ms")
            if result.get("error"):
                st.error(result["error"])
            for face in result.get("faces", []):
                st.write(f"**{face['name']}**")
                st.caption(face["label"])
                st.write(face["feedback"])
                if face.get("similarity") is not None:
                    st.caption(f"Cosine similarity: {face['similarity']:.3f}")

        feedback()
    st.subheader("Check-ins from this session")
    st.caption("To approve a camera check-in, go to Records → Review & correct.")

    @st.fragment(run_every=5)
    def recent():
        day = sessions[selected]["local_date"]
        rows = request("GET", "/attendance", params={"start": day, "end": day})
        st.dataframe(
            [
                {
                    "Name": row["full_name"],
                    "ID": row["institutional_id"],
                    "Status": row["status"].replace("_", " ").title(),
                    "Check-in": row["check_in"],
                }
                for row in rows
                if row["session_id"] == selected
            ],
            hide_index=True,
            use_container_width=True,
        )

    recent()
