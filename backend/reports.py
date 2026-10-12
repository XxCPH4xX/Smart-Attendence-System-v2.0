import csv
from datetime import date
from io import BytesIO, StringIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from sqlalchemy import select

from backend.db import utcnow
from backend.models import AttendanceRecord, AttendanceSession, Catalog, Person, PersonDetails

COLUMNS = [
    "record_id",
    "session_id",
    "session",
    "date",
    "institutional_id",
    "full_name",
    "category",
    "department",
    "status",
    "check_in",
    "check_out",
    "verification",
    "version",
]


def report_rows(
    db,
    start: date,
    end: date,
    category=None,
    department_id=None,
    person_id=None,
    class_id=None,
    section=None,
):
    query = (
        select(AttendanceRecord, AttendanceSession, Person, Catalog.name)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .join(Person, Person.id == AttendanceRecord.person_id)
        .outerjoin(Catalog, Catalog.id == Person.department_id)
        .outerjoin(PersonDetails, PersonDetails.person_id == Person.id)
        .where(AttendanceSession.local_date >= start, AttendanceSession.local_date <= end)
    )
    for condition, value in [
        (Person.category == category, category),
        (Person.department_id == department_id, department_id),
        (Person.id == person_id, person_id),
        (PersonDetails.class_id == class_id, class_id),
        (PersonDetails.section == section, section),
    ]:
        if value is not None:
            query = query.where(condition)
    rows = []
    for record, session, person, department in db.execute(
        query.order_by(AttendanceSession.local_date.desc(), Person.full_name)
    ):
        zone = ZoneInfo(session.timezone)
        rows.append(
            {
                "record_id": record.id,
                "session_id": session.id,
                "session": session.name,
                "date": session.local_date.isoformat(),
                "institutional_id": person.institutional_id,
                "full_name": person.full_name,
                "category": person.category,
                "department": department or "Unassigned",
                "status": record.status,
                "check_in": record.check_in.astimezone(zone).isoformat() if record.check_in else "",
                "check_out": record.check_out.astimezone(zone).isoformat()
                if record.check_out
                else "",
                "verification": record.verification,
                "version": record.version,
            }
        )
    return rows


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_report(rows, kind, institution, filters):
    generated = utcnow().isoformat()
    if kind == "csv":
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Institution", safe_cell(institution)])
        writer.writerow(["Generated at (UTC)", generated])
        writer.writerow(["Filters", safe_cell(filters)])
        writer.writerow(COLUMNS)
        writer.writerows([[safe_cell(row[c]) for c in COLUMNS] for row in rows])
        return output.getvalue().encode("utf-8-sig"), "text/csv"
    output = BytesIO()
    if kind == "xlsx":
        with xlsxwriter.Workbook(
            output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}
        ) as book:
            sheet = book.add_worksheet("Attendance")
            bold = book.add_format({"bold": True, "bg_color": "#E8EEF2"})
            sheet.write_row(0, 0, ["Institution", institution])
            sheet.write_row(1, 0, ["Generated at (UTC)", generated])
            sheet.write_row(2, 0, ["Filters", filters])
            sheet.write_row(4, 0, COLUMNS, bold)
            for i, row in enumerate(rows, 5):
                sheet.write_row(i, 0, [row[c] for c in COLUMNS])
            sheet.set_column(0, len(COLUMNS) - 1, 22)
            sheet.freeze_panes(5, 0)
            if rows:
                sheet.autofilter(4, 0, len(rows) + 4, len(COLUMNS) - 1)
        return (
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(escape(institution) + " — Attendance", styles["Title"]),
        Paragraph(escape(filters), styles["Normal"]),
        Paragraph("Generated (UTC): " + generated, styles["Normal"]),
        Spacer(1, 12),
    ]
    columns = ["date", "session", "institutional_id", "full_name", "category", "status"]
    cells = [[Paragraph(c.replace("_", " ").title(), styles["Normal"]) for c in columns]]
    cells += [[Paragraph(escape(str(row[c])), styles["Normal"]) for c in columns] for row in rows]
    table = LongTable(cells, repeatRows=1, colWidths=[70, 140, 100, 165, 85, 130])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    story.append(table)
    SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=24, rightMargin=24).build(story)
    return output.getvalue(), "application/pdf"
