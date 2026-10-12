from dataclasses import dataclass

import numpy as np
from sklearn.neighbors import KNeighborsClassifier


def normalize(vectors):
    data = np.asarray(vectors, dtype=np.float32)
    if data.ndim not in (1, 2) or data.shape[-1] != 512 or not np.isfinite(data).all():
        raise ValueError("Expected finite 512-dimensional embeddings")
    norms = np.linalg.norm(data, axis=-1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError("A zero embedding cannot be normalized")
    return data / norms


@dataclass(frozen=True)
class Match:
    person_id: int | None
    similarity: float
    margin: float
    status: str


class RecognitionIndex:
    """Immutable snapshot; scores are cosine similarities, never probabilities."""

    def __init__(self, vectors, labels, version=0, method="cosine"):
        self.vectors = normalize(vectors) if len(vectors) else np.empty((0, 512), np.float32)
        self.labels = np.asarray(labels, dtype=np.int64)
        if len(self.vectors) != len(self.labels):
            raise ValueError("Every template must have an identity label")
        self.version = version
        self.method = method
        self.knn = None
        self.ann = None
        if method not in {"cosine", "knn", "ann"}:
            raise ValueError("Unsupported recognition method")
        if method == "knn" and len(labels):
            self.knn = KNeighborsClassifier(
                n_neighbors=min(3, len(labels)), metric="cosine", weights="distance"
            )
            self.knn.fit(self.vectors, self.labels)
        if method == "ann" and len(labels) >= 10:
            from pynndescent import NNDescent

            self.ann = NNDescent(
                self.vectors,
                metric="cosine",
                random_state=42,
                n_neighbors=min(30, len(labels) - 1),
                n_jobs=1,
            )
            self.ann.prepare()

    def match(self, vector, threshold=0.8, margin=0.08):
        query = normalize(vector)
        if not len(self.labels):
            return Match(None, 0, 0, "unknown")
        candidates = np.arange(len(self.labels))
        if self.ann is not None:
            indices, _ = self.ann.query(query[None], k=min(30, len(self.labels)))
            candidates = indices[0]
        similarities = self.vectors[candidates] @ query
        scores = {}
        for i, score in zip(candidates, similarities, strict=True):
            person_id = int(self.labels[i])
            scores[person_id] = max(scores.get(person_id, -1.0), float(score))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        person_id, best = ranked[0]
        gap = best - ranked[1][1] if len(ranked) > 1 else best + 1
        # Exact runner-up verification protects unknown rejection from ANN retrieval misses.
        if self.ann is not None:
            others = self.labels != person_id
            if others.any():
                gap = best - float((self.vectors[others] @ query).max())
        if best < threshold:
            return Match(None, best, gap, "unknown")
        if gap < margin:
            return Match(None, best, gap, "ambiguous")
        if self.knn is not None and int(self.knn.predict(query[None])[0]) != person_id:
            return Match(None, best, gap, "ambiguous")
        return Match(person_id, best, gap, "recognized")
