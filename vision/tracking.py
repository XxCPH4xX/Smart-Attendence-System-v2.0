from dataclasses import dataclass


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


@dataclass
class Track:
    box: tuple
    person_id: int | None
    first_seen: float
    last_seen: float
    observations: int = 1


class StabilityTracker:
    def __init__(self, observations=3, seconds=1.0, max_gap=2.0):
        self.required = observations
        self.seconds = seconds
        self.max_gap = max_gap
        self.tracks = []

    def update(self, detections, now):
        available = [t for t in self.tracks if now - t.last_seen <= self.max_gap]
        updated, stable = [], []
        for box, person_id in detections:
            matches = [(iou(box, t.box), i, t) for i, t in enumerate(available)]
            matches.sort(key=lambda item: item[0], reverse=True)
            track = None
            if matches and matches[0][0] > 0.35:
                _, index, track = matches[0]
                available.pop(index)
            if not track or track.person_id != person_id or person_id is None:
                track = Track(box, person_id, now, now)
            else:
                track.observations += 1
                track.box, track.last_seen = box, now
            updated.append(track)
            stable.append(
                person_id is not None
                and track.observations >= self.required
                and now - track.first_seen >= self.seconds
            )
        # Missing observations invalidate stability; a returning face starts a new streak.
        self.tracks = updated
        return stable
