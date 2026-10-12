import cv2
import numpy as np


def clamp_box(box, width, height):
    x1, y1, x2, y2 = box
    return (
        max(0, min(int(x1), width - 1)),
        max(0, min(int(y1), height - 1)),
        max(0, min(int(x2), width)),
        max(0, min(int(y2), height)),
    )


def align_face(rgb, landmarks, box, size=160):
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = clamp_box(box, width, height)
    if x2 - x1 < 20 or y2 - y1 < 20:
        raise ValueError("Face is too small or outside the image")
    points = np.asarray(landmarks, dtype=np.float32)
    if points.shape != (3, 2) or not np.isfinite(points).all():
        raise ValueError("Three finite alignment points are required")
    if any(not (x1 <= x <= x2 and y1 <= y <= y2) for x, y in points):
        raise ValueError("Alignment landmarks must lie inside the detected face")
    if np.linalg.norm(points[1] - points[0]) < 8:
        raise ValueError("Face angle or eye geometry is unsuitable")
    target = np.float32([[0.32, 0.38], [0.68, 0.38], [0.5, 0.61]]) * size
    transform = cv2.getAffineTransform(points, target)
    return cv2.warpAffine(
        rgb, transform, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101
    )


def quality(rgb_crop, face_size, min_size=70, min_blur=40):
    gray = cv2.cvtColor(rgb_crop, cv2.COLOR_RGB2GRAY)
    brightness = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if face_size < min_size:
        return False, "Move closer to the camera"
    if brightness < 40 or brightness > 220:
        return False, "Improve face lighting"
    if blur < min_blur:
        return False, "Hold still; face is blurred"
    return True, "Quality accepted"
