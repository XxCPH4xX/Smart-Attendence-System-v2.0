import time
import tracemalloc

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

from vision.recognition import RecognitionIndex, normalize


def validate_split(frame):
    required = {"identity", "capture_session", "split", "path"}
    if not required <= set(frame.columns):
        raise ValueError(f"Manifest needs columns: {sorted(required)}")
    if frame[list(required)].isnull().any().any():
        raise ValueError("Manifest fields cannot be empty")
    if not set(frame["split"]) <= {"enrollment", "validation", "test"}:
        raise ValueError("Split must be enrollment, validation or test")
    if set(frame["split"]) != {"enrollment", "validation", "test"}:
        raise ValueError("All three splits are required")
    if frame["path"].duplicated().any():
        raise ValueError("The same image cannot occur in more than one split")
    leakage = frame.groupby(["identity", "capture_session"])["split"].nunique()
    if (leakage > 1).any():
        raise ValueError("Capture sessions overlap enrollment, validation or test")
    enrolled = set(frame.loc[frame.split == "enrollment", "identity"])
    for split in ["validation", "test"]:
        identities = set(frame.loc[frame.split == split, "identity"])
        if not identities - enrolled:
            raise ValueError(f"{split} needs genuinely unknown identities")
        if not identities & enrolled:
            raise ValueError(f"{split} needs held-out captures of known identities")
    unknown_validation = set(frame.loc[frame.split == "validation", "identity"]) - enrolled
    unknown_test = set(frame.loc[frame.split == "test", "identity"]) - enrolled
    if unknown_validation & unknown_test:
        raise ValueError("Use disjoint unknown identities for validation and test")


def extract_manifest(frame, asset_dir, device="cpu"):
    from pathlib import Path

    from backend.biometrics import decode_image
    from vision.detection import FaceDetector
    from vision.embeddings import Embedder

    validate_split(frame)
    detector = FaceDetector(Path(asset_dir))
    embedder = Embedder(Path(asset_dir), device)
    vectors, seen = [], set()
    try:
        import hashlib

        for row in frame.itertuples():
            content = Path(row.path).read_bytes()
            fingerprint = hashlib.sha256(content).digest()
            if fingerprint in seen:
                raise ValueError("Duplicate image content found; split would leak")
            seen.add(fingerprint)
            faces = detector.detect(decode_image(content))
            if len(faces) != 1 or not faces[0].quality_ok:
                raise ValueError(f"Image failed one-face quality validation: {row.path}")
            vectors.append(embedder.extract([faces[0].crop])[0])
    finally:
        detector.close()
    return normalize(vectors)


def evaluate(index, queries, truth, threshold, margin):
    elapsed, predictions = [], []
    for vector in queries:
        started = time.perf_counter()
        result = index.match(vector, threshold, margin)
        elapsed.append((time.perf_counter() - started) * 1000)
        predictions.append(result.person_id if result.person_id is not None else -1)
    truth = np.asarray(truth)
    predicted = np.asarray(predictions)
    known, unknown = truth != -1, truth == -1
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="macro", zero_division=0
    )
    labels = sorted(set(truth) | set(predicted))
    return {
        "known_accuracy": float(accuracy_score(truth[known], predicted[known]))
        if known.any()
        else None,
        "precision_macro": float(precision),
        "recall_macro": float(recall),
        "f1_macro": float(f1),
        "false_acceptance_rate": float(np.mean(predicted[unknown] != -1))
        if unknown.any()
        else None,
        "false_rejection_rate": float(np.mean(predicted[known] == -1)) if known.any() else None,
        "known_misidentification_rate": float(
            np.mean((predicted[known] != truth[known]) & (predicted[known] != -1))
        )
        if known.any()
        else None,
        "unknown_detection_rate": float(np.mean(predicted[unknown] == -1))
        if unknown.any()
        else None,
        "latency_ms_median": float(np.median(elapsed)),
        "latency_ms_p95": float(np.percentile(elapsed, 95)),
        "confusion_labels": labels,
        "confusion_matrix": confusion_matrix(truth, predicted, labels=labels).tolist(),
        "known_samples": int(known.sum()),
        "unknown_samples": int(unknown.sum()),
    }


def compare(frame, vectors, target_far=0.01):
    """Choose thresholds on validation only, then measure the untouched test split."""
    validate_split(frame)
    vectors = normalize(vectors)
    if len(frame) != len(vectors):
        raise ValueError("Manifest and embedding counts differ")
    enrollment = frame.split.to_numpy() == "enrollment"
    validation = frame.split.to_numpy() == "validation"
    test = frame.split.to_numpy() == "test"
    identities = sorted(set(frame.loc[enrollment, "identity"]))
    mapping = {identity: i for i, identity in enumerate(identities)}
    labels = np.array([mapping.get(i, -1) for i in frame.identity])
    results = []
    for method in ["cosine", "knn", "ann"]:
        tracemalloc.start()
        started = time.perf_counter()
        index = RecognitionIndex(vectors[enrollment], labels[enrollment], method=method)
        build_ms = (time.perf_counter() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        candidates = []
        for threshold in np.arange(0.5, 0.951, 0.025):
            for margin in (0.04, 0.08, 0.12):
                metrics = evaluate(
                    index, vectors[validation], labels[validation], float(threshold), margin
                )
                if metrics["false_acceptance_rate"] <= target_far:
                    candidates.append((metrics["f1_macro"], float(threshold), margin))
        if not candidates:
            results.append(
                {"method": method, "error": "No validation threshold met the requested FAR"}
            )
            continue
        _, threshold, margin = max(candidates)
        metrics = evaluate(index, vectors[test], labels[test], threshold, margin)
        results.append(
            {
                "method": method,
                "threshold": threshold,
                "margin": margin,
                "index_build_ms": build_ms,
                "python_peak_memory_bytes": peak,
                "ann_approximate": index.ann is not None if method == "ann" else None,
                **metrics,
            }
        )
    return results


def distance_distributions(frame, vectors):
    embeddings = normalize(vectors)
    similarities = embeddings @ embeddings.T
    rows = []
    for i in range(len(frame)):
        for j in range(i + 1, len(frame)):
            rows.append(
                {
                    "kind": "within identity"
                    if frame.iloc[i].identity == frame.iloc[j].identity
                    else "between identities",
                    "cosine_distance": float(1 - similarities[i, j]),
                }
            )
    return pd.DataFrame(rows)
