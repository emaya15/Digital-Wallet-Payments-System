"""PDF and CSV statement writers (no database access)."""
import csv
from datetime import date
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TABLE_HEADERS = ["Date", "Reference", "Type", "Description", "Credit", "Debit", "Balance"]


def statement_password(name: str, date_of_birth: date) -> str:
    """First four letters of the name (lower case) + birth year."""
    letters = "".join(ch for ch in (name or "") if ch.isalpha())[:4].lower()
    return f"{letters}{date_of_birth.year}"


def _row_values(row: Dict) -> List[str]:
    return [
        row["date"],
        row["reference"],
        row["type"],
        row["description"],
        row["credit"],
        row["debit"],
        row["balance"],
    ]


def write_statement_csv(path: str, header: Dict[str, str], rows: List[Dict], summary: Dict[str, str]) -> str:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for key, value in header.items():
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(TABLE_HEADERS)
        for row in rows:
            writer.writerow(_row_values(row))
        writer.writerow([])
        for key, value in summary.items():
            writer.writerow([key, value])
    return path


def write_statement_pdf(
    path: str,
    password: str,
    header: Dict[str, str],
    rows: List[Dict],
    summary: Dict[str, str],
) -> str:
    """Write a password protected PDF statement (amounts in INR)."""
    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Digital Wallet Statement",
        encrypt=password,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph("Digital Wallet Statement", styles["Title"]), Spacer(1, 4 * mm)]

    header_table = Table([[k, v] for k, v in header.items()], colWidths=[45 * mm, 120 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story += [header_table, Spacer(1, 5 * mm)]

    summary_table = Table([[k, v] for k, v in summary.items()], colWidths=[45 * mm, 45 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        )
    )
    story += [summary_table, Spacer(1, 6 * mm)]

    data = [TABLE_HEADERS]
    for row in rows:
        values = _row_values(row)
        values[3] = values[3][:26]
        data.append(values)
    if not rows:
        data.append(["No transactions in this period", "", "", "", "", "", ""])
    widths = [30 * mm, 33 * mm, 24 * mm, 36 * mm, 18 * mm, 18 * mm, 21 * mm]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ALIGN", (4, 1), (6, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("All amounts are in INR. This is a system generated statement.", styles["Italic"]))
    doc.build(story)
    return path
