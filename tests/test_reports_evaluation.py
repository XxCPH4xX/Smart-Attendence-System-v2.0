from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from backend.reports import COLUMNS, export_report
from vision.evaluation import compare, validate_split


def test_exports_neutralize_spreadsheet_formulas():
    row = dict.fromkeys(COLUMNS, "")
    row.update(full_name='=HYPERLINK("https://example.org")', category="student", date="2026-10-12")
    content, _ = export_report([row], "csv", "Institution", "start: 2026-10-12")
    assert b"'=HYPERLINK" in content
    excel, _ = export_report([row], "xlsx", "Institution", "start: 2026-10-12")
    with ZipFile(BytesIO(excel)) as archive:
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")
    pdf, _ = export_report([row], "pdf", "Institution", "start: 2026-10-12")
    assert pdf.startswith(b"%PDF")


@pytest.mark.parametrize("kind", ["csv", "xlsx", "pdf"])
def test_export_api(client, attendance_session, person, kind):
    client.post(
        "/attendance/correct",
        json={
            "session_id": attendance_session["id"],
            "person_id": person["id"],
            "status": "absent",
            "reason": "Authorized attendance correction",
        },
    )
    day = attendance_session["local_date"]
    result = client.get("/reports/export", params={"start": day, "end": day, "kind": kind})
    assert result.status_code == 200
    assert len(result.content) > 100
    assert f"attendance.{kind}" in result.headers["content-disposition"]


def manifest():
    return pd.DataFrame(
        [
            {
                "identity": "known",
                "capture_session": "enroll",
                "split": "enrollment",
                "path": "a.jpg",
            },
            {
                "identity": "known",
                "capture_session": "validate",
                "split": "validation",
                "path": "b.jpg",
            },
            {
                "identity": "unknown_v",
                "capture_session": "validate",
                "split": "validation",
                "path": "c.jpg",
            },
            {"identity": "known", "capture_session": "test", "split": "test", "path": "d.jpg"},
            {"identity": "unknown_t", "capture_session": "test", "split": "test", "path": "e.jpg"},
        ]
    )


def test_split_requires_unseen_captures_and_unknowns():
    frame = manifest()
    validate_split(frame)
    frame.loc[1, "capture_session"] = "enroll"
    with pytest.raises(ValueError, match="overlap"):
        validate_split(frame)
    frame = manifest()
    frame.loc[2, "identity"] = "known"
    with pytest.raises(ValueError, match="unknown"):
        validate_split(frame)


def test_synthetic_evaluation_measures_actual_predictions():
    vectors = np.zeros((5, 512), np.float32)
    vectors[[0, 1, 3], 0] = 1
    vectors[2, 1] = 1
    vectors[4, 2] = 1
    results = compare(manifest(), vectors)
    for result in results:
        assert result["known_accuracy"] == 1
        assert result["false_acceptance_rate"] == 0
        assert result["unknown_samples"] == 1
        assert result["latency_ms_median"] > 0
