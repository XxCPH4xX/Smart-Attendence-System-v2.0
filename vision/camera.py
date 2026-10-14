import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import httpx


def draw_overlays(frame, faces):
    height, width = frame.shape[:2]
    for face in faces:
        x1, y1, x2, y2 = [int(v) for v in face["box"]]
        color = (118, 158, 45) if face.get("person_id") else (70, 155, 220)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        lines = [
            face.get("name", "Unknown"),
            face.get("label", "Identity not verified"),
            face.get("feedback", ""),
        ]
        top = max(0, min(y1 - 65, height - 66))
        left = max(0, min(x1, width - 310))
        cv2.rectangle(frame, (left, top), (min(width - 1, left + 310), top + 65), (28, 35, 42), -1)
        for index, line in enumerate(lines):
            # OpenCV's built-in font is ASCII. Full Unicode names remain visible in the side panel.
            text = line.encode("ascii", "replace").decode()[:44]
            cv2.putText(
                frame,
                text,
                (left + 5, top + 17 + index * 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                (245, 245, 245),
                1,
                cv2.LINE_AA,
            )
    return frame


class RemoteProcessor:
    """One pending inference at most; preview frames never queue behind inference."""

    def __init__(self, api_url, token, stream_id, interval=0.5, width=640, station=False):
        self.client = httpx.Client(
            base_url=api_url, headers={"Authorization": f"Bearer {token}"}, timeout=20
        )
        self.stream_id = stream_id
        self.station = station
        self.interval, self.width = interval, width
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recognition")
        self.pending = None
        self.lock = threading.Lock()
        self.last_submit = self.last_result = 0.0
        self.result = {"faces": [], "latency_ms": 0, "error": None}
        self.closed = False

    def infer(self, frame):
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return {"faces": [], "error": "Frame encoding failed"}
        try:
            response = self.client.post(
                f"/vision/streams/{self.stream_id}/frame",
                content=jpeg.tobytes(),
                headers={"Content-Type": "image/jpeg"},
            )
            if response.status_code in {401, 403, 404}:
                return {
                    "faces": [],
                    "stopped": True,
                    "error": "The camera session ended or was reset. Start the station again to resume check-ins.",
                }
            if response.status_code != 200:
                detail = response.json().get("detail", "Recognition unavailable")
                return {"faces": [], "error": str(detail)}
            return response.json()
        except (httpx.HTTPError, ValueError):
            return {"faces": [], "error": "Recognition service unavailable"}

    def recv(self, frame):
        import av

        image = frame.to_ndarray(format="bgr24")
        scale = min(1, self.width / image.shape[1])
        image = cv2.resize(image, (int(image.shape[1] * scale), int(image.shape[0] * scale)))
        now = time.monotonic()
        with self.lock:
            if self.closed:
                return av.VideoFrame.from_ndarray(image, format="bgr24")
            if self.pending and self.pending.done():
                self.result = self.pending.result()
                self.last_result = now
                self.pending = None
            if (
                not self.pending
                and not self.result.get("stopped")
                and now - self.last_submit >= self.interval
            ):
                self.pending = self.executor.submit(self.infer, image.copy())
                self.last_submit = now
            faces = self.result.get("faces", []) if now - self.last_result < 2 else []
        return av.VideoFrame.from_ndarray(draw_overlays(image, faces), format="bgr24")

    def snapshot(self):
        with self.lock:
            return dict(self.result)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        try:
            self.client.delete(f"/vision/streams/{self.stream_id}")
        except httpx.HTTPError:
            pass
        self.client.close()
