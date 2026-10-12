from dataclasses import dataclass
from pathlib import Path

import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from vision.alignment import align_face, clamp_box, quality


@dataclass
class Face:
    box: tuple[int, int, int, int]
    crop: np.ndarray | None
    quality_ok: bool
    feedback: str


class FaceDetector:
    def __init__(self, asset_dir: Path):
        detector_path = asset_dir / "blaze_face_short_range.tflite"
        landmark_path = asset_dir / "face_landmarker.task"
        if not detector_path.is_file() or not landmark_path.is_file():
            raise RuntimeError("Face models are missing. Run: attendance download-models")
        self.detector = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=python.BaseOptions(model_asset_path=str(detector_path)),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=0.65,
            )
        )
        # Landmark each detector ROI independently so multi-face alignment never crosses identities.
        self.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=str(landmark_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.65,
                min_face_presence_confidence=0.65,
            )
        )

    def detect(self, rgb, min_size=70, min_blur=40):
        height, width = rgb.shape[:2]
        result = self.detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        faces = []
        for detection in result.detections:
            b = detection.bounding_box
            pad = int(max(b.width, b.height) * 0.18)
            box = clamp_box(
                (
                    b.origin_x - pad,
                    b.origin_y - pad,
                    b.origin_x + b.width + pad,
                    b.origin_y + b.height + pad,
                ),
                width,
                height,
            )
            x1, y1, x2, y2 = box
            roi = np.ascontiguousarray(rgb[y1:y2, x1:x2])
            if not roi.size:
                continue
            landmarks = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=roi))
            if len(landmarks.face_landmarks) != 1:
                faces.append(Face(box, None, False, "Face landmarks unavailable"))
                continue
            lm = landmarks.face_landmarks[0]
            points = [[lm[i].x * (x2 - x1) + x1, lm[i].y * (y2 - y1) + y1] for i in (33, 263, 1)]
            points[:2] = sorted(points[:2], key=lambda p: p[0])
            try:
                crop = align_face(rgb, points, box)
                good, feedback = quality(crop, min(b.width, b.height), min_size, min_blur)
                faces.append(Face(box, crop, good, feedback))
            except ValueError as error:
                faces.append(Face(box, None, False, str(error)))
        return faces

    def close(self):
        self.detector.close()
        self.landmarker.close()
